"""测试阿里云百炼头部模型 API Key 响应速度。"""

import time
import requests
from typing import List, Dict

__test__ = False

# 头部模型列表（2026年5月最新）
MODELS = [
    # Qwen 3.6 系列（最新旗舰）
    "qwen3.6-max-preview",
    "qwen3.6-plus",
    "qwen3.6-flash",
    # Qwen 3.5 系列
    "qwen3.5-plus",
    "qwen3.5-flash",
    # 第三方头部模型
    "glm-5.1",
    "glm-5",
    "kimi-k2.6",
    "MiniMax-M2.5",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    # Qwen3 系列（上一代旗舰）
    "qwen3-max",
    "qwen3-235b-a22b",
]

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ENDPOINT = f"{BASE_URL}/chat/completions"

TEST_PROMPT = "你好，请用一句话介绍你自己。"


def test_single_model(api_key: str, model: str, timeout: int = 60) -> Dict:
    """测试单个模型的响应时间。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": TEST_PROMPT},
        ],
        "max_tokens": 100,
        "temperature": 0.1,
    }
    
    start_time = time.time()
    try:
        resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=timeout)
        elapsed = time.time() - start_time
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "model": model,
                "status": "success",
                "time_ms": round(elapsed * 1000, 2),
                "tokens": data.get("usage", {}).get("total_tokens", 0),
            }
        else:
            return {
                "model": model,
                "status": "error",
                "time_ms": round(elapsed * 1000, 2),
                "error": f"HTTP {resp.status_code}",
            }
    except requests.Timeout:
        elapsed = time.time() - start_time
        return {
            "model": model,
            "status": "timeout",
            "time_ms": round(elapsed * 1000, 2),
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "model": model,
            "status": "error",
            "time_ms": round(elapsed * 1000, 2),
            "error": str(e),
        }


def test_api_key(api_key: str, models: List[str], label: str) -> List[Dict]:
    """测试一个 API Key 在所有模型上的表现。"""
    print(f"\n{'='*80}")
    print(f"测试 API Key: {label} (sk-...{api_key[-8:]})")
    print(f"{'='*80}\n")
    
    results = []
    for idx, model in enumerate(models, 1):
        print(f"[{idx}/{len(models)}] 测试 {model}...", end=" ", flush=True)
        result = test_single_model(api_key, model)
        results.append(result)
        
        if result["status"] == "success":
            print(f"[OK] {result['time_ms']:.0f}ms ({result['tokens']} tokens)")
        elif result["status"] == "timeout":
            print(f"[FAIL] 超时 ({result['time_ms']:.0f}ms)")
        else:
            print(f"[FAIL] {result.get('error', '未知错误')}")
    
    return results


def print_comparison(key1_results: List[Dict], key2_results: List[Dict], 
                     key1_label: str, key2_label: str):
    """打印对比结果。"""
    print(f"\n\n{'='*110}")
    print("最终对比结果")
    print(f"{'='*110}")
    print(f"{'模型':<30} {key1_label:<25} {key2_label:<25} {'更快':<15}")
    print(f"{'-'*110}")
    
    key1_map = {r["model"]: r for r in key1_results}
    key2_map = {r["model"]: r for r in key2_results}
    
    all_models = sorted(set(list(key1_map.keys()) + list(key2_map.keys())))
    
    key1_wins = 0
    key2_wins = 0
    ties = 0
    
    for model in all_models:
        r1 = key1_map.get(model)
        r2 = key2_map.get(model)
        
        if r1 and r1["status"] == "success":
            k1_str = f"{r1['time_ms']:.0f}ms"
            k1_time = r1["time_ms"]
        else:
            k1_str = "失败/超时"
            k1_time = float('inf')
        
        if r2 and r2["status"] == "success":
            k2_str = f"{r2['time_ms']:.0f}ms"
            k2_time = r2["time_ms"]
        else:
            k2_str = "失败/超时"
            k2_time = float('inf')
        
        if k1_time < k2_time:
            faster = key1_label
            key1_wins += 1
        elif k2_time < k1_time:
            faster = key2_label
            key2_wins += 1
        else:
            faster = "平局"
            ties += 1
        
        print(f"{model:<30} {k1_str:<25} {k2_str:<25} {faster:<15}")
    
    print(f"\n{'-'*110}")
    print(f"总结: {key1_label} 胜出 {key1_wins} 次, {key2_label} 胜出 {key2_wins} 次, 平局 {ties} 次")
    
    # 计算平均响应时间（仅成功的请求）
    key1_success_times = [r["time_ms"] for r in key1_results if r["status"] == "success"]
    key2_success_times = [r["time_ms"] for r in key2_results if r["status"] == "success"]
    
    if key1_success_times:
        avg1 = sum(key1_success_times) / len(key1_success_times)
        print(f"{key1_label} 平均响应时间: {avg1:.0f}ms (成功 {len(key1_success_times)}/{len(key1_results)} 个模型)")
    
    if key2_success_times:
        avg2 = sum(key2_success_times) / len(key2_success_times)
        print(f"{key2_label} 平均响应时间: {avg2:.0f}ms (成功 {len(key2_success_times)}/{len(key2_results)} 个模型)")
    
    # 找出最快的模型
    all_success = []
    for r in key1_results + key2_results:
        if r["status"] == "success":
            all_success.append((r["model"], r["time_ms"]))
    
    if all_success:
        all_success.sort(key=lambda x: x[1])
        print(f"\n最快模型 TOP 5:")
        for model, t in all_success[:5]:
            print(f"  {model}: {t:.0f}ms")
    
    print(f"{'='*110}\n")


def main():
    """主测试函数。"""
    api_key_1 = "sk-630e7a3afa074d13917d362b80833c14"
    api_key_2 = "sk-9108b59e2c434e1282318144d6d92c1c"
    
    print("="*80)
    print("测试阿里云百炼头部模型 API Key 响应速度")
    print("="*80)
    print(f"测试模型数量: {len(MODELS)}")
    print(f"测试端点: {ENDPOINT}")
    print(f"模型列表: {', '.join(MODELS)}")
    
    # 测试第一个 API Key
    key1_results = test_api_key(api_key_1, MODELS, "Key1")
    
    # 测试第二个 API Key
    key2_results = test_api_key(api_key_2, MODELS, "Key2")
    
    # 打印对比结果
    print_comparison(key1_results, key2_results, "Key1", "Key2")


if __name__ == "__main__":
    main()
