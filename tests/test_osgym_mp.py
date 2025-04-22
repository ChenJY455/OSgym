import multiprocessing
import time
from osgym import OSGymEnvWorker

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RED = '\033[91m'
RESET = '\033[0m'
import requests

def run_env_worker(worker_id):
    resp = requests.get("http://localhost:20000/route")
    port = resp.json()["port"]
    
    print(f"{BLUE}Worker port: {port} starting...")
    env_config = {
        #'server_url': 'http://localhost:20000',
        'server_url': f'http://localhost:{port}',
        'json_dir': './env_jsons',
        'img_h': 1080,
        'img_w': 1920,
        'max_step': 100,
        'max_hist': 10,
        'timeout': 1000
    }
    
    print(f"{BLUE}Worker {worker_id} starting...{RESET}")
    start_time = time.time()
    env = OSGymEnvWorker(env_config)
    
    try:
        # Test basic functionality
        start_time = time.time()
        obs, meta_info = env.reset()
        reset_time = time.time() - start_time
        assert obs is not None
        assert meta_info is not None
        print(f"{YELLOW}Worker {worker_id} reset successful in {reset_time:.2f}s{RESET}")
        
        # Perform a simple action
        start_time = time.time()
        action = '<|think_start|><|think_end|><|action_start|>click(100,100)<|action_end|>'
        ret, meta_info = env.step(action)
        step1_time = time.time() - start_time
        for k, v in ret.items():
            if k not in ['obs', 'prev_obs']:
                print(f"Worker {worker_id} {k}: {v}")
        assert ret is not None
        assert meta_info is not None
        print(f"{YELLOW}Worker {worker_id} click step successful in {step1_time:.2f}s{RESET}")

        start_time = time.time()
        action = '<|think_start|><|think_end|><|action_start|>finish()<|action_end|>'
        ret, meta_info = env.step(action)
        step2_time = time.time() - start_time

        for k, v in ret.items():
            if k not in ['obs', 'prev_obs']:
                print(f"Worker {worker_id} {k}: {v}")
        assert ret is not None
        assert meta_info is not None
        assert ret['done']
        print(f"{GREEN}Worker {worker_id} finish successful in {step2_time:.2f}s{RESET}")
        
        # Keep the worker alive for a while to test stability
        time.sleep(5)
        
    except Exception as e:
        print(f"{RED}Worker {worker_id} encountered error {e}{RESET}")

if __name__ == '__main__':
    num_workers = 10
    processes = []
    
    print(f"{BLUE}Starting {num_workers} environment workers...{RESET}")
    
    # Create and start processes
    for i in range(num_workers):
        p = multiprocessing.Process(target=run_env_worker, args=(i,))
        processes.append(p)
        p.start()
        # Small delay between starting workers to avoid overwhelming the server
        time.sleep(0.5)
    
    # Wait for all processes to complete
    for p in processes:
        p.join()
    
    print(f"{GREEN}All workers completed{RESET}") 
