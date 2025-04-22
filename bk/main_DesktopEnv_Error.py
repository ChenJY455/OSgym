from contextlib import asynccontextmanager
import datetime
import logging
import os
import sys
import threading
import time
import uvicorn
import base64
import json
import fcntl
from pathlib import Path
from desktop_env.desktop_env import DesktopEnv
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List, Union
from fastapi import responses, Query

# 原始日志配置保持不变
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

datetime_str: str = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")

file_handler = logging.FileHandler(os.path.join("logs", "normal-{:}.log".format(datetime_str)), encoding="utf-8")
debug_handler = logging.FileHandler(os.path.join("logs", "debug-{:}.log".format(datetime_str)), encoding="utf-8")
stdout_handler = logging.StreamHandler(sys.stdout)
sdebug_handler = logging.FileHandler(os.path.join("logs", "sdebug-{:}.log".format(datetime_str)), encoding="utf-8")

file_handler.setLevel(logging.INFO)
debug_handler.setLevel(logging.DEBUG)
stdout_handler.setLevel(logging.INFO)
sdebug_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt="\x1b[1;33m[%(asctime)s \x1b[31m%(levelname)s \x1b[32m%(module)s/%(lineno)d-%(processName)s\x1b[1;33m] \x1b[0m%(message)s")
file_handler.setFormatter(formatter)
debug_handler.setFormatter(formatter)
stdout_handler.setFormatter(formatter)
sdebug_handler.setFormatter(formatter)

stdout_handler.addFilter(logging.Filter("desktopenv"))
sdebug_handler.addFilter(logging.Filter("desktopenv"))

logger.addHandler(file_handler)
logger.addHandler(debug_handler)
logger.addHandler(stdout_handler)
logger.addHandler(sdebug_handler)

logger = logging.getLogger("desktopenv.main")

class VMStateManager:
    _shared_lock = threading.Lock()
    _instance = None

    def __new__(cls):
        with cls._shared_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.cache_dir = Path("vm_cache")
        self.cache_dir.mkdir(exist_ok=True)
        
        self.available_path = self.cache_dir / "available.json"
        self.active_path = self.cache_dir / "active.json"
        self.vm_map_path = self.cache_dir / "vm_map.json"
        self.lock_path = self.cache_dir / "file.lock"

        self._init_file(self.available_path, list(range(50, -1, -1)))
        self._init_file(self.active_path, [])
        self._init_file(self.vm_map_path, {})

    def _init_file(self, path: Path, default):
        if not path.exists():
            with self._file_lock():
                path.write_text(json.dumps(default))

    def _file_lock(self):
        lock_file = open(self.lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return lock_file

    def _read_state(self, path: Path):
        with self._file_lock():
            return json.loads(path.read_text())

    def _write_state(self, path: Path, data):
        with self._file_lock():
            path.write_text(json.dumps(data))

    @property
    def available_vms(self) -> List[int]:
        return self._read_state(self.available_path)

    @property
    def active_vms(self) -> List[int]:
        return self._read_state(self.active_path)

    @property
    def vm_map(self) -> Dict[int, Any]:
        return {int(k): v for k, v in self._read_state(self.vm_map_path).items()}

    def allocate_vm(self, vm_id: int):
        available = self.available_vms
        active = self.active_vms
        
        if vm_id in available:
            available.remove(vm_id)
            active.append(vm_id)
            self._write_state(self.available_path, available)
            self._write_state(self.active_path, active)

    def release_vm(self, vm_id: int):
        available = self.available_vms
        active = self.active_vms
        
        if vm_id in active:
            active.remove(vm_id)
            available.append(vm_id)
            self._write_state(self.active_path, active)
            self._write_state(self.available_path, available)

    def update_vm_map(self, vm_id: int, data: dict):
        vm_map = self.vm_map
        vm_map[vm_id] = data
        self._write_state(self.vm_map_path, vm_map)

    def remove_vm_map(self, vm_id: int):
        vm_map = self.vm_map
        if vm_id in vm_map:
            del vm_map[vm_id]
            self._write_state(self.vm_map_path, vm_map)

# 初始化状态管理
vm_manager = VMStateManager()
vm_lock = threading.Lock()

class ResetRequest(BaseModel):
    task_config: Dict[str, Any]
    timeout: int

class StepRequest(BaseModel):
    action: str
    vm_id: int

class ShutdownRequest(BaseModel):
    vm_id: Union[int, str]

@asynccontextmanager
async def lifespan(app: FastAPI):
    time.sleep(5)
    yield

app = FastAPI(lifespan=lifespan)

def _get_available_vm() -> int:
    with vm_lock:
        available = vm_manager.available_vms
        if not available:
            raise Exception("No available VMs")
        vm_id = available[-1]
        vm_manager.allocate_vm(vm_id)
        
        logger.info(f"Allocated VM ID: {vm_id}")
        return vm_id

def _release_vm(vm_id: Union[int, str]):
    with vm_lock:
        if isinstance(vm_id, int):
            if vm_id <= 50:
                vm_manager.release_vm(vm_id)
                logger.info(f"Released VM ID: {vm_id}")
        elif vm_id == "all":
            active = vm_manager.active_vms.copy()
            for vid in active:
                vm_manager.release_vm(vid)
            logger.info("Released all VMs")

def _get_vm_env(vm_id: int) -> DesktopEnv:
    with vm_lock:
        if vm_id not in vm_manager.active_vms:
            raise Exception(f"VM ID {vm_id} not available")
        return DesktopEnv(
            provider_name="docker",
            action_space="os_gym",
            require_a11y_tree=False,
            os_type="Ubuntu",
        )

def _set_timeout(vm_id: int, timeout: int):
    with vm_lock:
        vm_manager.update_vm_map(vm_id, {
            "timeout": timeout,
            "lifetime": timeout
        })
        logger.info(f"Set timeout for VM ID {vm_id} to {timeout} seconds")

def _check_timeout():
    while True:
        with vm_lock:
            current_map = vm_manager.vm_map
            active = vm_manager.active_vms.copy()
            available = vm_manager.available_vms.copy()
            
            for vm_id in list(active):
                entry = current_map.get(vm_id, {})
                if not entry.get("visited", False):
                    entry["lifetime"] = max(0, entry.get("lifetime", 0) - 60)
                else:
                    entry["visited"] = False
                    entry["lifetime"] = entry.get("timeout", 0)
                
                if entry["lifetime"] <= 0:
                    available.append(vm_id)
                    active.remove(vm_id)
                    if vm_id in current_map:
                        del current_map[vm_id]
            
            vm_manager._write_state(vm_manager.active_path, active)
            vm_manager._write_state(vm_manager.available_path, available)
            vm_manager._write_state(vm_manager.vm_map_path, current_map)
        
        time.sleep(60)

# 以下保持原始API端点不变
@app.get("/screenshot")
async def screenshot(vm_id: int = Query(..., alias="vmId")):
    try:
        vm_env = _get_vm_env(vm_id)
        obs = vm_env.render()
        logger.info(f"Taking screenshot for VM ID: {vm_id}")
        return {
            "screenshot": base64.b64encode(obs),
            "vm_id": vm_id,
        }
    except Exception as e:
        logger.error(f"Error taking screenshot for VM ID {vm_id}: {e}")
        return responses.JSONResponse(status_code=400, content={"message": str(e)})

@app.post("/reset")
async def reset(request: ResetRequest):
    try:
        vm_id = _get_available_vm()
        task_config = request.task_config
        obs = _get_vm_env(vm_id).reset(task_config)
        _set_timeout(vm_id, request.timeout)
        logger.info(f"Resetting VM ID: {vm_id} with task config: {task_config}")
        return {
            "screenshot": base64.b64encode(obs["screenshot"]),
            "problem": obs["instruction"],
            "vm_id": vm_id,
        }
    except Exception as e:
        logger.error(f"Error resetting VM: {e}")
        return responses.JSONResponse(status_code=400, content={"message": str(e)})

@app.post("/step")
async def step(request: StepRequest):
    try:
        vm_id = request.vm_id
        vm_env = _get_vm_env(vm_id)
        action = request.action
        obs, reward, done, _ = vm_env.step(action)
        logger.info(f"Stepping VM ID: {vm_id} with action: {action}")
        if done:
            reward = vm_env.evaluate()
            _release_vm(vm_id)
        return {
            "screenshot": base64.b64encode(obs["screenshot"]),
            "is_finish": done,
            "reward": reward,
        }
    except Exception as e:
        logger.error(f"Error stepping VM ID {vm_id}: {e}")
        return responses.JSONResponse(status_code=400, content={"message": str(e)})

@app.post("/shutdown")
async def shutdown(request: ShutdownRequest):
    try:
        vm_id = request.vm_id
        _release_vm(vm_id)
        return {"vm_id": vm_id}
    except Exception as e:
        logger.error(f"Error shutting down VM ID {vm_id}: {e}")
        return responses.JSONResponse(status_code=400, content={"message": str(e)})

if __name__ == "__main__":
    if not os.path.exists("logs"):
        os.makedirs("logs")
    os.system("docker stop $(docker ps -aq) > /dev/null 2>&1")
    os.system("docker rm $(docker ps -aq) > /dev/null 2>&1")
    
    #timeout_thread = threading.Thread(target=_check_timeout, daemon=True)
    #timeout_thread.start()
    
    uvicorn.run(
        app="main:app",
        host="0.0.0.0",
        port=20000,
        workers=10,
    )