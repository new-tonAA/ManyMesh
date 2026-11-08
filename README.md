# ManyMesh

> **面向移动端的几何复杂度压缩与神经重建协同实时渲染方案**
> Perceptual geometry compression and temporal reconstruction for real-time rendering.

像 **MegaLights 通过采样解决光源数量爆炸**一样，ManyMesh 通过**几何压缩 + 神经重建**解决
模型面数爆炸：用类似 Nanite 的自适应几何压缩减少模型处理开销，再用轻量神经网络超分
恢复因几何简化造成的视觉损失，从而使普通移动设备能够实时渲染高复杂度 3D 资产。

> 把不可承受的计算复杂度转化为可控制的近似误差，再用重建技术补偿。

- 📄 **完整方案、实验设计与里程碑路线图：[MANYMESH.md](MANYMESH.md)**
- 🧱 **渲染底座**：[Google Filament](https://github.com/google/filament) —— 本仓库为其完整源码快照
  （上游提交 `4bcb2e4e5aa2fdba45b0db73dcb92f5dbfc38752`），详见 [MANYMESH.md §9.1](MANYMESH.md#91-仓库形态)

## 当前实现状态

- **已跑通**：属性感知 QEM、QEM 最优位置折叠（可生成新位置并插值 chart 法线/UV）、
  按焊接位置锁定 seam、按焊接位置去重 cut、带质量门的层次化 cluster DAG、CPU 运行时 cut、
  编辑器节省比例滑杆/质量档位、近细远粗开关、分页流式缓存、WinHTTP（Windows）/ CivetWeb（Android、iOS、Linux、macOS）Range 下载，以及
  独立 Vulkan 原型：compute cut selection、GPU 索引/间接命令生成、三 pass GPU 顶点压缩、
  indirect draw 和 visibility buffer。CPU 侧 cut 的 source 与 generated 顶点也会按实际
  引用压缩并重映射（`--compact-vertices`）。
- **拓扑回归（焊接后）**：torus `--target-ratio 0.2` 为 **400 / 1,152 = 34.72%**，
  boundary/non-manifold/duplicate/degenerate/flipped 全 0；monkey `--target-ratio 0.3` 为
  **4,712 / 15,744 = 29.93%**，`--target-ratio 0.2` 为 **4,162 / 15,744 = 26.44%**，
  boundary 与源一致（168）、其余缺陷全 0；sphere 与 cloth
  在 50% 目标下仍为 50.00%，也没有新增缺陷。跨 chart 的 UV 分歧现在拆成同位置多个
  generated vertex，不再拒绝或平均；`--corner-split-uv 0` 只用于 A/B。低于这些比例会被
  几何/属性质量门拒绝，算法不会用放松质量门来换取更低面数。
- **Corner collapse 优先级（本轮）**：`CornerSimplifier` 的优先队列不再按 QEM 成本排序，
  而是直接使用 placement 评分：局部双向表面偏差、UV/normal 损失、重心外插和最差三角形
  质量共同决定先塌哪条边。质量项权重 0.25 是 torus/monkey 扫描的平衡点；质量门、焊接
  boundary 集合和 chart UV 拆分都没有放宽。同目标下 torus **550 → 400 面**、monkey
  **7,124 → 6,244 面**；同面数 monkey（7,084 vs 7,124）为 **35.50 dB / 0.98590 vs
  34.61 dB / 0.98443**，平均绝对差也更低（0.002235 vs 0.002421）。代价是 monkey 离线
  DAG 构建约 3.1s → 4.5s，运行时 cut 仍为 0.0018 ms。对照图在
  `out/ab-monkey-priority-montage.png` 与 `out/ab-torus-priority-montage.png`。
  cut 顶点也同步下降：monkey 7,867 → 7,402，torus 625 → 562，移动端上传量更小。
  后续的属性 chart 选择修复进一步把 monkey 同目标降到 **4,712 / 4,162 面**。
- **属性误差 chart 选择（本轮新增）**：`measureCandidateErrors()` 的位置误差仍取真正最近的
  三角形，但 UV/normal 误差现在会在同一最近距离附近的候选三角形中，选择与源顶点 chart
  最匹配的那个。此前同位置的多份 seam 副本可能被 BVH 先访问到另一张 chart，导致
  `maxNormal` 出现 45–72°、`maxUv` 出现 0.55–0.68 的假异常值；质量阈值没有放宽。
  修复后仍保留 12 次类似数值的拒绝，没有为它们继续放宽门限。
  monkey `--target-ratio 0.3` 从 **6,244（39.66%）降到 4,712（29.93%）**，
  `--target-ratio 0.2` 到 **4,162（26.44%）**；group 属性拒绝 **80 → 12**，
  同参数 DAG 构建约 **4.47s → 3.23s**。同 6,244 面、960×720、同机位 A/B 相对高模为
  **27.10 dB / 0.97167 SSIM**，修复前同面数为 **25.24 dB / 0.92891**。
  26.44% 档视觉仍有明显面片感，但没有孔洞、翻面或新增边界；对照图在
  `out/ab-monkey-attrfix-ref.png`、`out/ab-monkey-attrfix-4162.png` 和
  `out/ab-monkey-attrfix-6244.png`。新增
  `AttributeMetricsSelectTheSourceChartAtADuplicatePosition` 回归。
- **Draw-call 合并（本轮实测）**：DAG cut 的连续索引区间现在会合并成一个 draw，primitive
  数量也跟随合并后的组数，而不是保留上千个空槽位。满细节 monkey cut（4,626 三角形）从
  **1,433 draws / 72.0 ms** 降到 **1 draw / 7.4 ms** CPU 稳态帧时（960×540，OpenGL，
  Intel Iris Xe）。50% cut 的 560 个节点合并为 183 draws，为 35.7 ms；加上
  `--compact-cut-indices` 把当前 cut 的 11,220 个索引按材质拼成一个 buffer 后回到
  **1 draw / 7.05 ms**。三条路径（逐节点、区间合并、索引压缩）的截图逐像素一致，
  max diff = 0。`--no-merge-draws` 保留逐节点路径用于性能对照。
- **OpenGL compute 后端修复**：`dispatchCompute` 之前既没有绑定延迟提交的 descriptor
  set，也没有在 dispatch 后插入内存屏障；同时 `OpenGLProgram` 把 SSBO 当作 UBO 用
  `glGetUniformBlockIndex` 查询，导致 storage block 永远找不到。现在按
  `GL_SHADER_STORAGE_BLOCK` 绑定、在 dispatch 前调用 `updateDescriptors()`、dispatch
  后插入覆盖 storage/vertex/index/indirect 的 `glMemoryBarrier`。`compute_test` 现在为
  Vulkan **7/7**、OpenGL **6 passed / 1 skipped**（`out/cmake-vulkan` 构建；Vulkan 必须
  在 `FILAMENT_SUPPORTS_VULKAN=ON` 的目录中运行）。新增用例验证 compute 写 SSBO 后
  fragment 能读到结果、Vulkan/OpenGL 的 GPU DAG cut 与 CPU 选择逐节点一致，以及 GLSL ES
  3.10 cut shader 可编译成 SPIR-V；它同时修掉了 descriptor set 在 compute commit 后被
  消费、graphics 无法重新绑定到另一个 bind point 的问题。
- **`mm_bench --gpu-cut` 后端接入**：距离/屏幕误差路径现在可以通过 Filament 私有
  `DriverApi` 在 OpenGL 和 Vulkan 上提交 compute cut，再调用 `assembleLodSelection()`
  复用与 CPU 相同的跨节点去重、材质和子网格装配。torus 两端实测均为
  `nodeMismatch=0 / triangleMismatch=0`（9 nodes、858 triangles）。首次 dispatch 约
  OpenGL **779 ms**、Vulkan **645 ms**，其中包含 glslang/驱动 shader 编译，不能当作稳定
  dispatch 延迟；同一 cut 的 CPU 选择约 **0.02–0.05 ms**。shader、`GpuLodCutParams`、
  counters 和 camera 数学已下沉到 `libs/manymesh`，sample 与 backend 回归使用同一份契约。
  当前实现仍会同步回读选择结果并在 CPU 重建几何，因此它是后端可行性验证，不是生产级
  GPU-driven 渲染路径；默认构建目录仍未启用 Vulkan。
- **后端 indirect draw**：`DriverAPI` 新增 `drawIndexedIndirect`，Vulkan 走
  `vkCmdDrawIndexedIndirect`，OpenGL 走 `glDrawElementsIndirect`。OpenGL 路径先用
  驱动私有的 scratch buffer 做一次 GPU 侧 `glCopyBufferSubData`，规避 Intel/WGL 驱动
  对异步上下文分配的 buffer 直接作为 indirect source 时返回 `GL_INVALID_OPERATION`
  的问题，全程不回读 CPU。新增回归用例验证 indirect command 能实际进入 fragment
  shader；Vulkan 与 OpenGL 均通过。
- **着色补偿**：`repairShadingNormals()` 只改着色法线，不改三角形；`--shade-crease` 控制
  接缝法线合并角度，`--shade-strength` 和 UI 滑杆控制补偿强度。`mm_bench --shade-auto`
  和 UI 的 “Auto strength (screen error)” 会按最坏屏幕误差自动选强度：<0.25 px 不修，
  ≥1 px 停在实测最优的 0.50。960×720 monkey 44.99% 档从 41.84 dB / 0.99494 提升到
  41.93 dB / 0.99535；满强度反而回落到 41.83 dB。torus 46.70% 档为
  45.81 → 45.91 dB、0.99825 → 0.99844 SSIM。硬表面建议 5° 或关闭，有机模型默认 10°。
- **细节法线**：`DetailBake` 可把高模丢失的微表面法线烘到 LOD 的 UV；当前“保留源法线抽稀”
  的 LOD 上默认不建议开启（monkey 45% 档 37.17 → 36.70 dB），适合雕刻高模到游戏低模的
  离线烘焙，不适合替代几何 LOD。轮廓、遮挡和几何位移不能靠着色恢复。
- **着色补偿的收益上限（45% 档复验）**：960×720、monkey 7,124 面、固定机位、`--no-shadows`，
  与 11,250 面的 DAG 满细节参考比较。轮廓 XOR 只占 **0.11%** 像素，却贡献 **68.3%** 的
  平方误差；两图共同覆盖区的 PSNR 仅 **37.24 dB**。在该内部区域，10°/auto 缝法线为
  **37.42 dB（+0.18）**，AO 0.50 为 37.28（+0.04），AO+细节法线 0.25 为 37.17（-0.07），
  roughness 0.40/0.60 为 36.25/36.62。结论：着色能稳定补回的是接缝法线和少量可见性，
  细节法线/粗糙度不能替代几何；要再提升，优先 MSAA、近细远粗或学习型重建。
- **着色补偿的分工与本轮新复验**：同一 45.25% 机位下，材质项主要改善共同覆盖区
  （缝法线 37.24 → 37.42 dB），而轮廓 XOR 仍占 68.3% 平方误差。把 LOD 和高模参考
  **都开 TAA**（60 帧收敛、同机位）得到 41.00 dB / SSIM 0.99160，低于无 AA 的
  42.50 / 0.99555；TAA 的时域 jitter 在静帧上只会把内部细节拖糊，不能补轮廓，因此
  “静态画质档”仍选 MSAA。项目已有的 20k 参数 `tiny` CNN（dragon 20.8% 训练）跨资产
  直接推理到 monkey 45.25% 档为 **42.50 → 42.65 dB**（SSIM 0.99555 → 0.99583），
  叠接缝法线为 **42.57 → 42.70 dB**；38.00% 档为 37.38 → 37.52 dB，叠 4× MSAA 为
  38.81 → 38.89 dB。它的整图收益来自轮廓/边缘（XOR 平方误差占比 68.3% → 64.1%），
  共同覆盖区反而降到 36.85 dB，说明学习型重建是“边缘合成”，不是材质 AO 的替代品；
  同资产训练的 tiny 模型在 dragon 上可到 +1.88 dB，跨资产只剩 +0.15 dB，训练数据
  与资产覆盖才是上限。复验图与 JSON 在 `out/temporal-check/`。
- **推荐的着色补偿阶梯**：≥45% 保留率用“10°/auto 缝法线 + 顶点 AO 0.5”（高模参考
  也必须使用同一种 AO 表达）；25–45% 用“4× MSAA + 缝法线”，AO 只在
  `--shade-error-driven` 下按 cluster 误差淡入，细节法线/roughness/POM 默认关闭；
  <25% 不再靠材质拉强度，改用近细远粗、几何质量门、高模阴影代理或学习型重建。
  这也是 UI “Use measured preset for this cut” 的判据。`mm_bench --auto-shading-preset`
  和 UI 的 “Auto apply measured preset” 会在每次 cut 变化后自动执行这条阶梯，手动滑杆
  仍可随后覆盖；这样开发者不需要在每次调整减面比例后手动点预设。
  同一判据已下沉为 `recommendedShadingCompensationPreset(retainedRatio, hasCompensation)`
  （`manymesh/ShadingNormals.h`），供编辑器/运行时直接复用并有单测覆盖。
- **一键 LOD 着色补偿（opt-in，UI 可实时 A/B）**：`mm_bench --shade-compensate` 使用
  `aiLodCompensated`，把高模 AO 贴图与 DAG 顶点 AO 取 `min`，并可选叠加高模→当前 cut 的
  细节法线与高度/视差。`--compensation-strength 0..1` 是总强度；UI 勾选
  “Shading compensation (AO + detail)” 或按 `C` 即可即时开关，另有两个滑杆分别调细节法线
  和 roughness，POM 强度和层数也走同一总闸门。交互模式让组合材质常驻，强度 0 与普通渲染视觉一致（实测 69.9 dB，只有
  0.2% 像素因 `specularAntiAliasing` 有极小差异），所以开关不需要重建材质或 renderable。
  UI 的 **Use measured AO preset (45%+)** 会把实测可重复的 AO 0.50 组合一键恢复；当当前
  保留率低于 45% 时会提示优先 MSAA、不要继续加 AO/细节法线。
  无 UV、平铺 UV 或越界 UV 时自动回退到顶点 AO，不再只得到白色 AO 贴图。
  3 模型 × 3 视角、960×720、同 AO 表达参考：monkey 45% 为 **45.83 → 46.36 dB**
  （+0.53 dB，SSIM 0.99700 → 0.99812）；torus 43% 为 **45.70 → 45.69 dB**（中性）；
  cloth 47% 为 **38.54 → 44.12 dB**（+5.58 dB，自动顶点 AO 回退路径）。
  AO-only 仍是默认；monkey 三视角细节法线为 45.36 dB（-1.00 dB），
  roughness +0.10 为 42.42 dB（-3.94 dB），所以两者只做美术开关。着色补不了轮廓、
  薄几何、接触几何和位移，只补表面可见性与微法线响应；比较时必须让高模和 LOD 使用同一种
  AO 表达（顶点对顶点、贴图对贴图），否则指标会被参考系反转。
- **按 cluster 屏幕误差调节着色补偿（新增，opt-in）**：`--shade-error-driven` 和 UI 的
  “Error-driven per cluster” 把每个 DAG 节点的补偿权重写进顶点色 alpha：低于 0.25 px
  自动淡出，1 px 达到满强度，近处已经足够细的 cluster 不再被 AO/细节法线过度压暗，
  远处的粗 cluster 继续补偿。`compensationStrength` 仍是总闸门，0 会关闭全部补偿。
  单物体 monkey 50% 档（640×360、128² AO、16 rays）与全局补偿相比为
  **43.76 → 43.73 dB**，基本中性；它不是 PSNR 收益项，而是混合近远 cluster 时的
  稳定性策略，默认关闭。接入自定义材质时必须保留顶点色 alpha 作为补偿权重；
  组合材质也默认启用 `specularAmbientOcclusion : simple`，让 AO 同时衰减高光 IBL，
  并可选择读取顶点色 G/B 的 bent normal。
- **运行时代替/补充烘焙的屏幕空间遮挡（新增，opt-in）**：`mm_bench --ssao` 走 Filament
  GTAO，`--ssct` 在同一个 pass 里加主光方向的 cone-trace 接触阴影；UI 有 GTAO、SSCT、
  半径、强度、质量、Half/Full 分辨率档位。它只看当前 cut 的深度缓冲，不需要 UV 或离线烘焙，
  适合没有源 UV、或运行时动态 cut 的资产。**必须和高模参考使用同一种 SSAO 表达**；它
  只乘间接光，需要 `--ibl`（或真实环境光）才看得到。960×720、同机位 3–4 视角：cloth
  48% 档无 SSAO **44.82 dB**，GTAO **44.85**，GTAO+SSCT **45.04**（+0.22）；monkey
  45% 档 GTAO **41.68 → 41.72**（+0.08）；torus 47.7% 为 **39.19 → 39.20**（中性）。
  半分辨率 Medium 的 cloth 结果与全分辨率 High 相同（45.04 dB），960×720 的 GPU 增量从
  **+2.48 ms 降到 +0.88 ms**，移动端优先这档。SSAO/SSCT 补的是当前几何仍能表达的
  褶皱和接触暗部，不能恢复轮廓、薄几何或已经被删掉的腔体。
- **极限 LOD 的着色上限（29.38% monkey 实测）**：同一机位、同 AO 表达参考下，29.38% 档
  基线 **39.78 dB / 0.99159**；加 AO 为 39.81 dB（+0.03），再加 1024² 细节法线降到
  39.46 dB（-0.35），正视 POM 无可见变化。误差拆分显示轮廓 XOR 仅占 **0.19%** 像素却贡献
  **66.7%** 平方误差，±2 px 带占 1.03% / 72.7%；轮廓内部 PSNR 仍有 35.16 dB。结论：
  着色能补 AO/微法线/掠射位移，补不了覆盖与几何错位；该档要靠几何门、近细远粗或时域重建，
  不能靠把补偿强度拉满。
  如果高模与 LOD 都开 **MSAA**，同一档（默认材质、1024×640）从无 AA 的
  **39.76 dB / 0.99159** 提升到 **2× 40.87 dB / 0.99221**、**4× 41.40 dB / 0.99262**
  （参考也开同样的 MSAA）。这说明抗锯齿能补回一部分轮廓像素，但不能恢复被删掉的几何：
  LOD 的眼窝、鼻翼和耳朵轮廓仍然可见地变粗。移动端建议先试 2×，4× 的带宽/填充成本更高。
  静态机位 TAA 反而降到 37.92 dB（模糊/历史污染），本轮不作为收益项。
  对照图：`out/shadecomp-monkey29/montage_msaa.png`。
- **26.44% 档：着色补偿已经饱和（本轮新增）**：monkey 4,162 面、960×720、固定机位、
  `--no-shadows`。基线 **26.37 dB / 0.96480**；10°/auto 缝法线 PSNR 仍为 **26.37 dB**，
  SSIM 提到 **0.96567**；顶点 AO 0.5 反而降到 **25.14 dB / 0.95846（-1.23 dB）**，
  目视在下巴/脸颊形成块状暗斑；4× MSAA（参考同开）为 **26.39 dB / 0.96541**，
  叠加缝法线为 **26.38 dB / 0.96606**。这个机位下模型占画面更大，MSAA 的 PSNR 收益
  远小于 29.38% 的 1024×640 机位（+0.02 vs +1.64 dB），说明 AA 收益强烈依赖屏幕覆盖率，
  不能跨机位套用。结论：26% 档不要再加 AO/细节法线/roughness，只保留缝法线（SSIM）
  和按预算可选的 MSAA；轮廓/耳廓/眼窝的缺失只能靠几何门、近细远粗或学习型重建。
  对照图：`out/shade26/montage_26.png`，JSON：`out/shade26/shading.json`、
  `out/shade26/msaa.json`、`out/shade26/within.json`。
- **高模阴影代理（新增，opt-in）**：`mm_bench --shadow-proxy` 让源网格（默认 ratio 1.0）
  或更细的 DAG cut 只参加阴影贴图，不写主相机颜色和深度；材质
  `samples/materials/shadowProxy.mat` 用 `colorWrite:false` / `depthWrite:false` 实现。
  UI 勾选 “High-poly shadow proxy” 或按 `P` 即时 A/B，`Shadow proxy detail` 控制代理
  三角形比例，`Shadow bias` / `Shadow normal bias` 用来消除 LOD 接收面与高模投影面
  之间的 self-shadow acne（默认 0.010 m / 3.0，对应太阳默认 0.001 m / 1.0）。
  实测 monkey 55% 档只改变 **0.35%** 像素，45% 档也基本中性（PSNR 略降约 0.01–0.04 dB）：
  单物体自阴影在 1024 阴影图下已经被 LOD 近似得很好，这条路径的价值在“高模角色把细节
  轮廓投到地面/其他物体”等跨物体接触阴影，而不是单物体 PSNR。它仍然不能补回屏幕空间
  轮廓覆盖，且会增加一次高模阴影深度绘制，所以默认关闭。
- **38.00% 档的着色收益复测（新增）**：monkey 5,982 面、960×720、`--no-shadows`，高模与 LOD
  使用同一材质和同一参考表达。无 AA 为 **37.38 dB / 0.98135**；两边都开 4× MSAA 为
  **38.81 dB / 0.98342**（+1.43 dB）。AO 在其 AO 参考系下从 36.61 提到 **37.33 dB /
  0.98023**（+0.72 dB），再叠细节法线 0.25 回落到 37.28 dB；AO + 4× MSAA 为 38.69 dB，
  没有比单独 MSAA 更高。目视上 38% 档的 AO 会把下巴/颈部的大三角形放大成块状暗斑，因此
  推荐该档优先抗锯齿，AO 只在 45% 以上或完整 IBL 管线中按距离淡入，细节法线继续默认关闭。
  对照图：`out/shadecomp38/montage_38.png`。
  固定同一相机重测（`--dag --savings 0.62`，960×720）时，无 AA 为 41.81 dB / 0.99323，
  4× MSAA 为 42.07 dB / 0.99355，10°/auto 缝法线为 41.94 dB / 0.99383，两者叠加为
  **42.17 dB / 0.99401**。因此 UI 的 measured preset 在 <45% 档选 MSAA + 缝法线，AO、
  细节法线、POM 保持关闭；>=45% 档才切到 AO 0.5。
- **极限 LOD 的几何落点（本轮新增）**：`CornerSimplifier` 不再按 QEM 成本取第一个合法
  落点，而是在 keep/remove 端点、中点、QEM 最优点及其切平面/源三角形投影之间统一评分。
  评分同时约束双向局部表面偏差、邻接三角形平面偏差、UV/normal 误差、重心外插量和 QEM
  成本；原有 `worldError`、最小质量和边界门均未放宽。torus 1,152 面、3/4 机位、4× MSAA
  下，旧压力档 338 面为 31.86 dB / 0.98370，QEM-first 444 面为 32.49 dB / 0.98693；
  当前默认 452 面（39.2%）为 **33.89 dB / 0.98773**，代价是多 1.8% 面数，换来 +1.40 dB
  和更完整的环体轮廓。着色仍补不了这处被切掉的几何，所以极端档应优先保证落点质量，
  而不是把 AO/法线强度拉满。对照图：`out/torus-lod-montage-final.png`。
  同路径 DAG 参考下复测着色补偿：monkey 44.00% 档 **43.28 → 43.39 dB**（SSIM
  0.99511 → 0.99549），cloth 48.06% 档 **40.74 → 40.78 dB**（0.99046 → 0.99083）。
  10°/auto 缝法线稳定为正，但量级只有 0.04–0.11 dB；cloth 大三角造成的块状起伏仍在，
  说明它修的是接缝和 shading discontinuity，不是低模本身的几何起伏。
- **高度/视差补偿**：`mmgeo --bake-height N` 在共享 UV 上比较源表面与 LOD 表面，输出
  `detail-height.png` 和推荐视差尺度；`aiLodCompensated.mat` 已内置迭代视差，
  `aiParallax.mat` 仍可单独使用。monkey 45% 档单视角仅 40.39 → 40.45 dB，4 视角中位数不升反微降
  （42.40 → 42.38 dB），因此默认关闭，只适合源资产本身有真实位移/微表面细节的情况。
- **丢失法线方差 → 逐纹素粗糙度（新增，opt-in）**：`DetailBake` 把高模法线与 LOD 法线的
  夹角归一化后写进 `detail-normal.png` 的 alpha；`aiLodCompensated.mat` 的
  `roughnessBoost` 只在该纹素确实丢了法线细节时生效，而不是给整个资产统一加粗糙度。
  这修的是“高光比剩余几何更锐”的统计错误，不能恢复被删掉的形状；旧的三通道贴图仍按
  alpha=1 兼容，因此已有资产的行为不变。
  45.25% monkey cut 的 256² 烘焙里，丢失角平均只有 **1.02°**，alpha 平均 1.59/255，
  34.0% 纹素非零，alpha>32 的只有 257/65,536；`roughnessBoost=0.5` 与 0 的对照为
  **41.088 → 41.094 dB**，仅 0.008% 像素变化超过 1 LSB（最大 10 LSB）。把 alpha 人为
  设成 255 后同一对照降到 48.9 dB、1.86% 像素变化，证明路径有效。结论：该项在
  45%+ 档基本是 no-op，只在真正激进的 cut 上起保护作用，不会把近档高光磨钝。
- **源网格 AO 烘焙（顶点与 UV 贴图两条路径）**：`AmbientOcclusion` 用 BVH 半球采样把高模
  腔体可见性烘到 LOD 顶点（`--bake-ao`，不需要 UV）或烘进源 UV atlas
  （`--ao-map-size N` / `mmgeo --bake-ao-map N`，材质 `aiBakedAoMap`）。两条路径都只补
  接触阴影，不能补轮廓、薄几何或位移。
- **方向性可见性（bent normal，新增）**：同一批半球射线在统计标量 AO 的同时累加未遮挡
  方向，得到顶点 bent normal，并与 AO 一起打包进 `UBYTE4` 顶点色（R=AO，G/B=切线空间
  xy）。`aiBakedAo` 把它写入 `material.bentNormal`，驱动方向性 diffuse IBL 和
  `specularAmbientOcclusion : bentNormals`。monkey 45% cut 上平均倾斜 8.4°、最大 89.6°；
  `--bent-normal-strength 0/1` 的 A/B 为平均 0.15/255、最大 16/255、PSNR 50.1 dB，
  差异集中在眼窝/鼻翼/耳廓。它不是 PSNR 收益项：对同样开 bent normal 的高模参考，
  强度 0 → 1 会让 LOD 的 PSNR 从 39.59 降到 38.98 dB（SSIM 0.99436 → 0.99300），
  所以默认强度 0，只在需要方向性环境光时通过 UI/CLI 打开。**赋值必须放在
  `prepareMaterial()` 之前**，否则 Filament
  缓存的 `shading_bentNormal` 仍是默认的 (0,0,1)，强度滑杆会完全无效。UI 新增
  Bent normal / IBL intensity / Sun intensity 滑杆，`--sun-intensity 0` 可只看着色补偿。
  它仍然补不了轮廓、薄几何和真实位移；生产资产不应复用已有顶点色，建议改写到
  `CUSTOM0` 或独立 attribute。
- **AO 贴图的噪声与分辨率**：32-sample 估计有可见 texel 噪点，默认 `smoothingPasses=1`
  的 3×3 Gaussian 只在 covered texel 内平滑，再向 chart 外扩 4 texel，因此不会跨 chart
  串色。monkey 44.99% 档的贴图 AO 从 41.77 提到 41.82 dB，目视更干净。512 与 1024 的
  源 AO 贴图渲染结果 PSNR 为 57.8 dB（平均绝对差 0.0285/255），烘焙却从 0.61 s 涨到
  2.34 s、显存 4 倍，默认保留 512。
  `mm_bench --ao-map-size` 现在在 headless 路径也会真正烘焙；要让 LOD 使用高模 AO，仍应
  用 `mmgeo --bake-ao-map` 预烘，而不是在 LOD 文件上重烘。
- **AO 的结论必须带参考系**：之前记录的 monkey 55% 档 41.64 → **44.92 dB** 是相对于
  **同样开了 AO 的高模参考**（材质一致）；同样两张图对**未开 AO 的高模参考**时，AO 会把
  逐像素 PSNR 从 42.51 降到 41.77（贴图）或 40.45（顶点）。因此 AO 是“让低模匹配高模的
  材质响应”，不是凭空恢复未阴影的高模外观。两条路径也不能混用：参考用顶点 AO 时顶点 AO
  比贴图高 2.9 dB；参考用贴图 AO 时贴图比顶点高 1.0 dB。生产时应让高模和 LOD 采样同一种
  AO 表达。贴图 AO 在 55%/45%/38% 三档只比顶点 AO 高 0.04–0.08 dB，但它是带 UV 资产
  的标准做法；tiled/越界 UV 仍回退到顶点 AO。
- **Cavity 实验**：`samples/materials/aiCavity.mat` 用屏幕空间平均曲率压暗凹处，
  `mm_bench --shade-cavity`/UI 滑杆可调（需显式使用该材质，且场景要有 IBL 或阴影）。
  保留源法线的 LOD 上实测偏负（monkey 45% 档
  36.29 → 34.85 dB @ 0.25），因为它压暗的是低模折面而非高模丢掉的细节，所以默认关闭；
  源网格 AO 已经验证有效，下一步是高度/位移或时域重建，而不是继续加屏幕空间强度。
- **性能**：cloth 7 级 DAG（74,976 三角形，corner seam 开启）本轮从 8.42s 降到 6.63s
  （-21.3%）。corner 候选不再每次重拷整个共享网格，焊接拓扑门只遍历当前 unit 引用的顶点；
  DAG 节点、三角形、cut 和拓扑统计逐位不变，monkey 截图逐像素一致。历史上的 17.2s →
  10.3s 优化（locked-mask、BVH、并行）仍保留。运行时 CPU cut 为亚毫秒级，UI 滑杆可实时
  切换 cut。
- **extended-mesh 复用（本轮新增）**：`simplifyClusterInto` 过去在每个 cluster/group 调用
  开始时复制整张共享网格。现在同一构建批次用一个内部 `meshCacheEpoch` 复用 base
  positions/normals/UVs/AO，只重写 generated 尾部，并只快照质量门真正读取的顶点属性。
  同一台机器、同一 cloth 命令（74,976 三角形、9 级、`--target-ratio 0.5`）总构建
  **21.07s → 18.63s（-11.6%）**；`extended-mesh` 计时 **3.25s / 2197 次复制 → 0.28s /
  120 次复制**。DAG 的 `1986 nodes / 9 levels / 37488 drawn`、节点索引、误差和拓扑
  统计逐位不变；monkey 同路径也保持 `413 nodes / 7124 drawn / worst 20.2738 px`。
  新增 `CachedExtendedMeshDoesNotChangeSimplifiedOutput` 回归，`test_manymesh` 现为
  **76 个测试（75 PASS + 1 环境 SKIP）**；另新增属性 chart 选择和着色补偿档位单测。
- **corner 落点评估优化（本轮新增）**：串行 profile 显示 cloth 的 `corner target` 占
  **49.1s**（1113 万次落点评分），是最大热点。现在每个落点只计算一次重心权重，
  三角形质量与法线共用一次叉积，并用端点距离、三角形平面距离和
  “表面误差下界仍打不过当前最优”做严格剪枝。同一 cloth 命令的串行总时间
  **101.19s → 85.93s（-15.1%）**，`target` **49.08s → 32.64s（-33.5%）**，
  `evaluate` **63.58s → 49.34s（-22.4%）**；DAG 的
  `1971 nodes / 7 levels / 37488 drawn / worst 8.8090 px`、生成顶点数和全部拓扑统计
  逐位不变，`.mmb` 的 SHA256 与优化前完全相同。默认并行构建
  **18.63s → 15.81s（-15.1%，多次运行 15.8–16.5s）**，输出仍是
  `1986 nodes / 9 levels / 37488 drawn / worst 7.8916 px`，哈希同样一致。
- **顶点内存**：cut 上传现在同时压缩 source 与 generated。monkey balanced cut
  22,268 → 7,516 顶点（33.8%），torus 1,706 → 502（29.4%），sphere 10,647 → 2,019
  （19.0%）；压缩路径与全量路径的截图逐像素 diff = 0，流格式 v4/v5/v6 均可读取。
- **尚未完成**：Filament **公共 API** 中的持久 storage buffer / compute dispatch /
  indirect draw 入口（后端 `VulkanDriver::dispatchCompute`、compute pipeline 和
  `drawIndexedIndirect` 均已实现，`compute_test` 在 Vulkan 上 5/5、OpenGL 上 4/5
  （1 skipped）通过；但应用层还没有公共句柄）、
  把 mmgpu 的 visibility buffer 接进 Filament 正式渲染器，以及移动端真机 GPU、HTTP
  transport、功耗与帧时验证。GPU 侧 cut 压缩已在独立原型中完成，不再需要 CPU 回读后
  重建 index/indirect/vertex buffer；便携 HTTP Range transport 已由 CivetWeb 覆盖
  Android/iOS/Linux/macOS（HTTPS 取决于平台是否提供 TLS 运行时）。

> ⚠️ **构建前请注意**：本仓库的 Windows 构建流程与上游默认方式不同（Filament 不支持 MSYS2
> 环境），并含一处 MSVC 编译修补。请先阅读
> [MANYMESH.md §9 开发环境与构建](MANYMESH.md#9-开发环境与构建当前状态)。

---

# Filament

[![Android Build Status](https://github.com/google/filament/actions/workflows/status-android.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-android.yml)
[![iOS Build Status](https://github.com/google/filament/actions/workflows/status-ios.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-ios.yml)
[![Linux Build Status](https://github.com/google/filament/actions/workflows/status-linux.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-linux.yml)
[![macOS Build Status](https://github.com/google/filament/actions/workflows/status-macos.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-macos.yml)
[![Windows Build Status](https://github.com/google/filament/actions/workflows/status-windows.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-windows.yml)
[![Web Build Status](https://github.com/google/filament/actions/workflows/status-web.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-web.yml)

Filament is a real-time physically based rendering engine for Android, iOS, Linux, macOS, Windows,
and WASM. It is designed to be as small as possible and as efficient as possible on Android.

## Download

[Download Filament releases](https://github.com/google/filament/releases) to access stable builds.
Filament release archives contains host-side tools that are required to generate assets.

Make sure you always use tools from the same release as the runtime library. This is particularly
important for `matc` (material compiler).

If you'd rather build Filament yourself, please refer to our [build manual](/BUILDING.md).

### Android

Android projects can simply declare Filament libraries as Maven dependencies:

```gradle
repositories {
    // ...
    mavenCentral()
}

dependencies {
    implementation 'com.google.android.filament:filament-android:1.77.3'
}
```

Here are all the libraries available in the group `com.google.android.filament`:

| Artifact      | Description   |
| ------------- | ------------- |
| [![filament-android](https://img.shields.io/maven-central/v/com.google.android.filament/filament-android?label=filament-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filament-android)  | The Filament rendering engine itself. |
| [![filament-android-debug](https://img.shields.io/maven-central/v/com.google.android.filament/filament-android-debug?label=filament-android-debug&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filament-android-debug)  | Debug version of `filament-android`. |
| [![gltfio-android](https://img.shields.io/maven-central/v/com.google.android.filament/gltfio-android?label=gltfio-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/gltfio-android) | A glTF 2.0 loader for Filament, depends on `filament-android`. |
| [![filament-utils-android](https://img.shields.io/maven-central/v/com.google.android.filament/filament-utils-android?label=filament-utils-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filament-utils-android) | KTX loading, Kotlin math, and camera utilities, depends on `gltfio-android`. |
| [![filamat-android](https://img.shields.io/maven-central/v/com.google.android.filament/filamat-android?label=filamat-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filamat-android) | A runtime material builder/compiler. This library is large but contains a full shader compiler/validator/optimizer and supports both OpenGL and Vulkan. |

### iOS

iOS projects can use CocoaPods to install the latest release:

```shell
pod 'Filament', '~> 1.77.3'
```

## Documentation

- [Filament](https://google.github.io/filament/Filament.html), an in-depth explanation of
  real-time physically based rendering, the graphics capabilities and implementation of Filament.
  This document explains the math and reasoning behind most of our decisions. This document is a
  good introduction to PBR for graphics programmers.
- [Materials](https://google.github.io/filament/Materials.html), the full reference
  documentation for our material system. This document explains our different material models, how
  to use the material compiler `matc` and how to write custom materials.
- [Material Properties](https://google.github.io/filament/notes/material_properties.html), a reference
  sheet for the standard material model.

## Examples

![Night scene](docs/images/samples/example_bistro1.jpg)
![Night scene](docs/images/samples/example_bistro2.jpg)
![Materials](docs/images/samples/example_materials1.jpg)
![Materials](docs/images/samples/example_materials2.jpg)
![Helmet](docs/images/samples/example_helmet.jpg)
![Screen-space refraction](docs/images/samples/example_ssr.jpg)

## Features

### APIs

- Native C++ API for Android, iOS, Linux, macOS and Windows
- Java/JNI API for Android
- JavaScript API

### Backends

- OpenGL 4.1+ for Linux, macOS and Windows
- OpenGL ES 3.0+ for Android and iOS
- Metal for macOS and iOS
- Vulkan 1.0 for Android, Linux, macOS, and Windows
- WebGPU for Android, Linux, macOS, and Windows
- WebGL 2.0 for all browsers supporting it

### Rendering

- Clustered forward renderer
- Cook-Torrance microfacet specular BRDF
- Lambertian diffuse BRDF
- Custom lighting/surface shading
- HDR/linear lighting
- Metallic workflow
- Clear coat
- Anisotropic lighting
- Approximated translucent (subsurface) materials
- Cloth/fabric/sheen shading
- Normal mapping & ambient occlusion mapping
- Image-based lighting
- Physically-based camera (shutter speed, sensitivity and aperture)
- Physical light units
- Point lights, spot lights, and directional light
- Specular anti-aliasing
- Point, spot, and directional light shadows
- Cascaded shadows
- EVSM, PCSS, DPCF, or PCF shadows
- Colored penumbra
- Transparent shadows
- Contact shadows
- Screen-space ambient occlusion
- Screen-space reflections
- Screen-space refraction
- Global fog
- Dynamic resolution (with support for AMD FidelityFX FSR)

### Post processing

- HDR bloom
- Depth of field bokeh
- Multiple tone mappers: GT7, PBR Neutral, AgX, generic (customizable), ACES, filmic, etc.
- Color and tone management: luminance scaling, gamut mapping
- Color grading: exposure, night adaptation, white balance, channel mixer,
  shadows/mid-tones/highlights, ASC CDL, contrast, saturation, etc.
- TAA, FXAA, MSAA
- Screen-space lens flares

### glTF 2.0

- Encodings
  - [x] Embeded
  - [x] Binary

- Primitive Types
  - [x] Points
  - [x] Lines
  - [ ] Line Loop
  - [x] Line Strip
  - [x] Triangles
  - [x] Triangle Strip
  - [ ] Triangle Fan

- Animation
  - [x] Transform animation
  - [x] Linear interpolation
  - [x] Morph animation
    - [x] Sparse accessor
  - [x] Skin animation
  - [x] Joint animation

- Extensions
  - [x] KHR_draco_mesh_compression
  - [x] KHR_lights_punctual
  - [x] KHR_materials_clearcoat
  - [x] KHR_materials_dispersion
  - [x] KHR_materials_emissive_strength
  - [x] KHR_materials_ior
  - [x] KHR_materials_pbrSpecularGlossiness
  - [x] KHR_materials_sheen
  - [x] KHR_materials_specular
  - [x] KHR_materials_transmission
  - [x] KHR_materials_unlit
  - [x] KHR_materials_variants
  - [x] KHR_materials_volume
  - [x] KHR_mesh_quantization
  - [x] KHR_texture_basisu
  - [x] KHR_texture_transform
  - [x] EXT_meshopt_compression

## Rendering with Filament

### Native Linux, macOS and Windows

You must create an `Engine`, a `Renderer` and a `SwapChain`. The `SwapChain` is created from a
native window pointer (an `NSView` on macOS or a `HWND` on Windows for instance):

```c++
Engine* engine = Engine::create();
SwapChain* swapChain = engine->createSwapChain(nativeWindow);
Renderer* renderer = engine->createRenderer();
```

To render a frame you must then create a `View`, a `Scene` and a `Camera`:

```c++
Camera* camera = engine->createCamera(EntityManager::get().create());
View* view = engine->createView();
Scene* scene = engine->createScene();

view->setCamera(camera);
view->setScene(scene);
```

Renderables are added to the scene:

```c++
Entity renderable = EntityManager::get().create();
// build a quad
RenderableManager::Builder(1)
        .boundingBox({{ -1, -1, -1 }, { 1, 1, 1 }})
        .material(0, materialInstance)
        .geometry(0, RenderableManager::PrimitiveType::TRIANGLES, vertexBuffer, indexBuffer, 0, 6)
        .culling(false)
        .build(*engine, renderable);
scene->addEntity(renderable);
```

The material instance is obtained from a material, itself loaded from a binary blob generated
by `matc`:

```c++
Material* material = Material::Builder()
        .package((void*) BAKED_MATERIAL_PACKAGE, sizeof(BAKED_MATERIAL_PACKAGE))
        .build(*engine);
MaterialInstance* materialInstance = material->createInstance();
```

To learn more about materials and `matc`, please refer to the
[materials documentation](https://google.github.io/filament/Materials.html).

To render, simply pass the `View` to the `Renderer`:

```c++
// beginFrame() returns false if we need to skip a frame
if (renderer->beginFrame(swapChain)) {
    // for each View
    renderer->render(view);
    renderer->endFrame();
}
```

For complete examples of Linux, macOS and Windows Filament applications, look at the source files
in the `samples/` directory. These samples are all based on `libs/filamentapp/` which contains the
code that creates a native window with SDL2 and initializes the Filament engine, renderer and views.

For more information on how to prepare environment maps for image-based lighting please refer to
[BUILDING.md](/BUILDING.md#running-the-native-samples).

### Android

See `android/samples` for examples of how to use Filament on Android.

You must always first initialize Filament by calling `Filament.init()`.

Rendering with Filament on Android is similar to rendering from native code (the APIs are largely
the same across languages). You can render into a `Surface` by passing a `Surface` to the
`createSwapChain` method. This allows you to render to a `SurfaceTexture`, a `TextureView` or
a `SurfaceView`. To make things easier we provide an Android specific API called `UiHelper` in the
package `com.google.android.filament.android`. All you need to do is set a render callback on the
helper and attach your `SurfaceView` or `TextureView` to it. You are still responsible for
creating the swap chain in the `onNativeWindowChanged()` callback.

### iOS

Filament is supported on iOS 11.0 and above. See `ios/samples` for examples of using Filament on
iOS.

Filament on iOS is largely the same as native rendering with C++. A `CAEAGLLayer` or `CAMetalLayer`
is passed to the `createSwapChain` method. Filament for iOS supports both Metal (preferred) and
OpenGL ES.

## Assets

To get started you can use the textures and environment maps found respectively in
`third_party/textures` and `third_party/environments`. These assets are under CC0 license. Please
refer to their respective `URL.txt` files to know more about the original authors.

Environments must be pre-processed using
[`cmgen`](/BUILDING.md#running-the-native-samples) or
using the `libiblprefilter` library.

## How to make contributions

Please read and follow the steps in [CONTRIBUTING.md](/CONTRIBUTING.md). Make sure you are
familiar with the [code style](/CODE_STYLE.md). For reporting vulnerabilities, please consult
our [Security Policy](/SECURITY.md).

## Directory structure

This repository not only contains the core Filament engine, but also its supporting libraries
and tools.

- `android`:                  Android libraries and projects
  - `filamat-android`:        Filament material generation library (AAR) for Android
  - `filament-android`:       Filament library (AAR) for Android
  - `filament-utils-android`: Extra utilities (KTX loader, math types, etc.)
  - `gltfio-android`:         Filament glTF loading library (AAR) for Android
  - `samples`:                Android-specific Filament samples
- `art`:                      Source for various artworks (logos, PDF manuals, etc.)
- `assets`:                   3D assets to use with sample applications
- `build`:                    CMake build scripts
- `docs`:                     Documentation
  - `math`:                   Mathematica notebooks used to explore BRDFs, equations, etc.
- `filament`:                 Filament rendering engine (minimal dependencies)
  - `backend`:                Rendering backends/drivers (Vulkan, Metal, OpenGL/ES)
- `ide`:                      Configuration files for IDEs (CLion, etc.)
- `ios`:                      Sample projects for iOS
- `libs`:                     Libraries
  - `bluegl`:                 OpenGL bindings for macOS, Linux and Windows
  - `bluevk`:                 Vulkan bindings for macOS, Linux, Windows and Android
  - `camutils`:               Camera manipulation utilities
  - `filabridge`:             Library shared by the Filament engine and host tools
  - `filaflat`:               Serialization/deserialization library used for materials
  - `filagui`:                Helper library for [Dear ImGui](https://github.com/ocornut/imgui)
  - `filamat`:                Material generation library
  - `filamentapp`:            SDL2 skeleton to build sample apps
  - `filameshio`:             Tiny filamesh parsing library (see also `tools/filamesh`)
  - `geometry`:               Mesh-related utilities
  - `gltfio`:                 Loader for glTF 2.0
  - `ibl`:                    IBL generation tools
  - `image`:                  Image filtering and simple transforms
  - `imageio`:                Image file reading / writing, only intended for internal use
  - `matdbg`:                 DebugServer for inspecting shaders at run-time (debug builds only)
  - `math`:                   Math library
  - `mathio`:                 Math types support for output streams
  - `utils`:                  Utility library (threads, memory, data structures, etc.)
  - `viewer`:                 glTF viewer library (requires gltfio)
- `samples`:                  Sample desktop applications
- `shaders`:                  Shaders used by `filamat` and `matc`
- `third_party`:              External libraries and assets
  - `environments`:           Environment maps under CC0 license that can be used with `cmgen`
  - `models`:                 Models under permissive licenses
  - `textures`:               Textures under CC0 license
- `tools`:                    Host tools
  - `cmgen`:                  Image-based lighting asset generator
  - `filamesh`:               Mesh converter
  - `glslminifier`:           Minifies GLSL source code
  - `matc`:                   Material compiler
  - `matedit`:                Material editor for compiled materials
  - `matinfo`                 Displays information about materials compiled with `matc`
  - `mipgen`                  Generates a series of miplevels from a source image
  - `normal-blending`:        Tool to blend normal maps
  - `resgen`                  Aggregates binary blobs into embeddable resources
  - `roughness-prefilter`:    Pre-filters a roughness map from a normal map to reduce aliasing
  - `specular-color`:         Computes the specular color of conductors based on spectral data
- `web`:                      JavaScript bindings, documentation, and samples

## License

Please see [LICENSE](/LICENSE).

## Disclaimer

This is not an officially supported Google product.
