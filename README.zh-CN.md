# ManyMesh

ManyMesh 是 Filament 仓库中的网格细节层次（LOD）研究原型，用来测量简化几何对画质和渲染成本的影响。**目前没有经过验证的 SIGGRAPH 级方法，也没有经过真机验证的移动端性能结论。**

## 项目动机

最初的提案是“面向移动端的几何复杂度压缩与神经重建协同实时渲染”：用几何简化减少处理量，再尝试重建简化带来的画质损失。这是历史研究设想，不代表当前方法或已验证的移动端方案。

> 早期构想的口号是“把不可承受的计算复杂度转化为可控制的近似误差，再用重建技术补偿”。它表达的是研究动机，不是实验结论。

当前唯一在跟进的方法假设是：离线优化受拓扑和簇边界约束的 cluster-LOD，并在最终抗锯齿或超分流程之后评估画质。它仍未通过实验门槛；相关工作和证据见[研究状态](MANYMESH.md)、[SIGGRAPH 方向](SIGGRAPH_2027_DIRECTION.md)及[先行工作审查](docs/manymesh/siggraph-prior-art-screen-20261123.md)。

## 已有证据

- 在 21 个 Poly Haven 模型、相同面数和 24 组视角/距离条件下，当前 ManyMesh 切片的 PSNR 平均比 meshoptimizer 低 **2.27 dB**；详细结果同时报告 LDR-FLIP、PSNR、SSIM、轮廓 XOR、表面距离和法线一致性。见[质量报告](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md)。
- 同一模型集的轮廓 XOR 区域承载了平方灰度误差的 **31.0%**（无 AA）和 **16.3%**（4× MSAA）。这是事后几何误差分解，不是感知指标，也不能推广为所有模型的规律。见[分析](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md)。
- 本机 D 盘 WSL2 下，`test_manymesh` 为 94 项通过、1 项跳过；Vulkan `compute_test` 的 7 项均在 llvmpipe 软件设备上通过。OpenGL 软件路径有 3 项中止；Iris Xe 路径因 Filament feature level 不足而跳过 7 项，因此硬件 GPU compute 仍未验证。见[本机验证记录](tools/mmtrain/LOCAL_WORKSTATION_VERIFICATION_20261126.md)。

CPU 全 RGB 拟合的 CI 工件尚未完成独立指标审计；移动端、功耗、等完整帧时间的 MSAA/SMAA/超分对比、用户偏好和跨资产优化收益均未测量。英文首页列出[实验条件和研究索引](README.md)。
