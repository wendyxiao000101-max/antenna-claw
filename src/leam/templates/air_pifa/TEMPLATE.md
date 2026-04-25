---
template_id: air_pifa
name: 空气介质 PIFA
version: "1.0"
antenna_type: PIFA
substrate: air
baseline_frequency_ghz: 2.4
entry_class: AirPifaTemplate
entry_module: scripts
match_keywords:
  - "PIFA"
  - "pifa"
  - "平面倒F"
match_substrate:
  - "air"
  - "空气"
editable_params:
  - Lp
  - Wp
  - h
  - sPins
  - Lg
  - Wg
locked_params:
  - t_cu
  - dPin
  - gPort
---

# 空气介质 PIFA 天线模板

## 适用场景

- 辐射贴片与地平面之间为空气介质的 PIFA 天线
- 单频设计，基准频率 2.4 GHz，可缩放至其他频率
- 固定拓扑：矩形贴片 + 短路针 + 馈电针（离散端口）

## 拓扑来源

基于已验证的 CST history list，固定以下结构：

- GroundPlane (Brick, Copper annealed)
- RadiatingPatch (Brick, Copper annealed)
- ShortingPin (Cylinder, Copper annealed)
- FeedPin_Bottom + FeedPin_Top (Cylinder, Copper annealed)
- FeedPort_Gap (Cylinder, Vacuum)
- Boolean: Add 操作合并导体
- DiscretePort: 50 Ohm

## 参数说明

| 参数名  | 单位 | 说明                         | 可调 |
|---------|------|------------------------------|------|
| t_cu    | mm   | 铜箔厚度                     | 锁定 |
| Lg      | mm   | 地平面长度 (X)               | 可调 |
| Wg      | mm   | 地平面宽度 (Y)               | 可调 |
| h       | mm   | 贴片距地平面高度             | 可调 |
| Lp      | mm   | 辐射贴片长度 (X)             | 可调 |
| Wp      | mm   | 辐射贴片宽度 (Y)             | 可调 |
| dPin    | mm   | 短路针 / 馈电针直径          | 锁定 |
| sPins   | mm   | 馈电针与短路针中心 Y 轴间距  | 可调 |
| gPort   | mm   | 离散端口间隙 (Z)             | 锁定 |

## 频率缩放策略

基于 PIFA 谐振公式 `f = c / (4 * (Lp + Wp - Ws))`：

- Lp, Wp 按频率反比缩放
- sPins 随 Wp 同比缩放
- Lg, Wg 按缩放比调整并保持 >= 2*Lp, >= 2*Wp
- h, t_cu, dPin, gPort 保持不变

## 目录结构

```
air_pifa/
├── TEMPLATE.md                    # 本文件
├── data/
│   └── optimized_pifa_params.json # baseline 几何参数（2.4 GHz 优化后）
├── reference/
│   ├── PIFA建模.bas               # 完整 CST VBA 宏（单文件拓扑参考）
│   └── README.md
├── scripts/                       # 运行时代码：匹配 / 校验 / 生成 / 交互编辑
│   ├── __init__.py                # AirPifaTemplate 入口类
│   ├── pifa_base.py               # 基线加载 + 频率缩放
│   ├── pifa_generator.py          # 6 个产物文件的确定性生成器
│   ├── pifa_review.py             # 参数表渲染 + 交互编辑
│   └── pifa_validator.py          # 参数校验规则
└── examples/
    ├── input_2p4ghz.json          # 示例调用输入
    ├── generate_expected.py       # 重新生成 expected_output/ 的辅助脚本
    └── expected_output/           # baseline 对应的 6 个产物样例
```

`reference/PIFA建模.bas` 是拓扑的权威来源；`scripts/pifa_generator.py` 的输出应与之在几何/布尔层面保持一致。
