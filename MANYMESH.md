# ManyMesh —— 面向移动端的几何复杂度压缩与神经重建协同实时渲染方案

> **一句话版本**
>
> ManyMesh 提出一种面向移动端的**几何-图像联合优化渲染框架**：通过类似 Nanite 的自适应几何压缩减少模型处理开销，并结合轻量神经网络超分技术恢复因几何简化造成的视觉损失，从而使普通移动设备能够实时渲染高复杂度 3D 资产。

> **核心思想**
>
> 像 **MegaLights 通过采样解决光源数量爆炸**一样，**ManyMesh 通过几何压缩 + 神经重建解决模型面数爆炸**。
>
> 把不可承受的计算复杂度，转化为可控制的近似误差，再用重建技术补偿。

---

## 1. 目标问题

移动端游戏 / 应用面临：

- 高质量角色模型
- 超大场景资产
- 扫描模型（photogrammetry / NeRF 导出）

导致：

```text
模型面数 ↑
   ↓
Vertex Processing ↑
Memory Bandwidth ↑
GPU 压力 ↑
   ↓
移动端无法实时运行
```

传统解法是**手工 LOD**：

```text
手工 LOD → 降低面数 → 画质下降
```

ManyMesh 的目标：

> 在减少**实际渲染几何量**的同时，通过**智能重建**恢复视觉质量。

---

## 2. 总体 Pipeline

```text
                 High Poly Asset
                       |
                       v
        ┌─────────────────────────┐
        │   ManyMesh Geometry     │
        │   Optimization          │
        └─────────────────────────┘
                       |
          Cluster 化 / Mesh Simplification
                       |
                       v
              Low Complexity Mesh
                       |
                       v
              Mobile Renderer
              (Google Filament)
                       |
                       v
            Low Resolution Rendering
                       |
                       v
        ┌─────────────────────────┐
        │  Neural Reconstruction  │
        │  (Mobile Lightweight    │
        │   CNN)                  │
        └─────────────────────────┘
                       |
                       v
              High Quality Image
```

---

## 3. 第一部分：移动端 Nanite 思想（Geometry Virtualization）

**注意：不是实现完整 UE Nanite。** UE Nanite 包含 cluster hierarchy、virtualized
geometry、streaming、software rasterizer，体量太大。

本课题的目标是实现一个 **Mobile Geometry Optimization Layer**。

### Step 1 — Mesh Cluster 化

输入例如 500 万三角形的角色模型，拆分为若干 cluster：

```text
Cluster 0 : 1000 triangles
Cluster 1 : 1000 triangles
Cluster 2 : 1000 triangles
...
```

每个 cluster 记录：`bounding box`、`error metric`、`triangle 数量`。

### Step 2 — 屏幕空间误差选择

传统 LOD 按距离切换（`distance > 50m → LOD2`）。
ManyMesh 按**屏幕空间误差 + 最终视觉影响**决定：

```text
近 → 保留更多 cluster
远 → 删除 cluster
```

### Step 3 — 几何简化

使用成熟算法（QEM / Mesh Simplification）：

```text
500 万 triangles → 50 万 triangles
```

输出：低复杂度 mesh。

---

## 4. 第二部分：移动端神经重建

思想类似 DLSS：**不恢复几何，而是恢复最终图像。**

### 输入（不只给 RGB）

利用实时渲染的天然优势，提供多 buffer 输入：

```text
Low Resolution Color
+ Depth Buffer
+ Normal Buffer
+ Motion Vector
+ Geometry Error Map     ← 本方案的特色
```

其中 **Geometry Error Map** 告诉网络：哪些区域因降面产生了误差。

```text
原模型：脸部 50000 triangles
优化后：脸部  5000 triangles
              ↓
Error Map：脸部区域误差较大
```

### 网络

采用轻量 CNN（如 RenderSR / Mob-FGSR 一类），而非大模型。
目标体量：**几十 KB ~ 几 MB**，可在手机上实时运行。

```text
Input → Tiny CNN → Residual Detail → Final Frame
```

---

## 5. 第三部分：联合优化（真正的创新点）

普通流水线：

```text
Geometry → Rendering → Image
```

ManyMesh：

```text
Geometry
   ↓
预计视觉损失
   ↓
Neural Reconstruction 能力
   ↓
决定 Geometry 压缩程度
```

例如：

| 场景 | 网络恢复难度 | 策略 |
|-|-|-|
| 静止建筑 | 易恢复 | 允许更低 poly |
| 高速运动角色 | 难恢复 | 保留更多 geometry |

形成动态策略：

```text
Geometry Budget + Neural Reconstruction Capability → Optimal Rendering Cost
```

---

## 6. 实验设计

| 方案 | 配置 |
|-|-|
| Baseline 1（原始高模） | 500 万 triangles，1080p rendering |
| Baseline 2（传统 LOD） | 50 万 triangles，720p |
| **ManyMesh** | 50 万 triangles + Neural Reconstruction → 接近 1080p 质量 |

### 指标

| 指标 | 意义 |
|-|-|
| FPS | 性能 |
| GPU time | 计算成本 |
| Memory | 移动端压力 |
| Triangle count | 几何减少 |
| PSNR / SSIM / LPIPS | 画质 |
| 功耗 | 移动端适配 |

---

## 7. 里程碑路线图（长期目标）

> 这是长期课题，不可能一次完成。以下为分阶段目标。

- [x] **M0 — 基础设施**
  - 拉取 Filament 源码树（本仓库）
  - Windows 桌面编译链打通（核心库 + 工具链 + 可运行样例）
- [x] **M1 — 基础渲染与度量基线**（首个切片，见 §7.2）
  - [x] 找到并接入**超多面数测试场景**（Stanford Asian Dragon，7,219,045 三角面）
  - [x] 离线渲染 harness `samples/mm_bench`（固定相机/材质/曝光，无 UI，headless）
  - [x] 画质度量 `tools/mmmetrics/compare.py`（PSNR / SSIM，LPIPS 可选）与 GPU 帧时采集
  - [x] 跑出 Baseline 2（传统 LOD）的面数-画质-帧时真实数据
  - [ ] LPIPS 接入；多视角统计；移动端真机（功耗/发热）
- [x] **M2 — 几何侧：Mobile Geometry Optimization Layer**（首个切片，见 §7.1）
  - 离线 mesh cluster 化 + 每 cluster 的 error metric
  - 屏幕空间误差驱动的 cluster 选择
  - QEM / mesh simplification 生成低复杂度 mesh（全局链 + 逐 cluster 两种模式）
  - 产出 **Geometry Error Map**（离线软件光栅化原型）
  - cluster 组（cluster group）简化：平均误差降低 43%，但最差误差仍未追平全局链
  - [x] 属性接缝保护：按共享索引拆分 UV/法线 chart，分组只沿共享顶点邻接生长，避免跨接缝简化
  - [x] 跨 UV/法线 chart 的成对 seam collapse：同位置的两侧边界顶点一起收缩，并用焊接位置拓扑验证不产生裂缝
  - [x] 六模型同机位视觉回归：dragon / sphere / monkey / torus / cloth / shapes 未发现新增穿孔
  - [x] 层次化 cluster DAG：每个 cluster 保留自己的 LOD 链，组父节点再逐级合并（见 §7.6）
  - [x] 运行时 CPU 选层：非重叠 DAG cut，O(节点数) 遍历；`selectLodGraphCut` 不组装索引
  - [x] 编辑器 UI：节省比例滑杆、Maximum/Balanced/Aggressive 档位、近细远粗开关
  - [x] 质量门：边界边集合、非流形边、重复/退化/翻转三角形、最小三角形质量、世界空间位置误差
  - [x] normal/UV 参与 attribute QEM；material/submesh ID 保留到 DAG 节点和 draw primitive
  - [x] 本地文件分页 + 可插拔异步 page fetcher + LRU 缓存；GPU 侧有 std430 布局和间接绘制数据结构
  - [x] 真实 Vulkan 原型：compute shader DAG cut + `vkCmdDrawIndexedIndirect` + R32_UINT/D32 visibility buffer
  - [x] Windows 生产网络 transport：`HttpByteRangeFetcher`（WinHTTP，HTTP/HTTPS + Range + 重定向）
  - [x] 便携网络 transport：Android/iOS/Linux/macOS 默认使用 vendored CivetWeb（HTTP Range；
        HTTPS 需要平台提供 TLS 运行时），`-DMANYMESH_HTTP_CIVETWEB=OFF` 可改用注入式 `RangeFetcher`
  - [ ] 移动端真机 HTTP/HTTPS 与网络切换验证
- [ ] **M3 — 图像侧：移动端轻量神经重建**（首个切片，见 §7.3）
  - [x] 配对数据生成（多视角、同一相机列表、逐视角误差图）
  - [x] 轻量 CNN 重建：等分辨率下比粗几何高 **+1.88 dB**；半分辨率下比双三次高 **+0.98 dB**
  - [x] 与已发表轻量超分网络（ESPCN / FSRCNN）在同等小数据预算下对比
  - [x] 消融：**Geometry Error Map 目前没有带来有意义的收益**（−0.19 ~ +0.13 dB，符号不定）
  - [x] **时域累积（见 §8.5）**：亚像素抖动 + 多帧累积，与学习互补，合计 **+1.35 dB**
  - [x] **真时域**（见 §8.6）：pan + 精确旋转重投影，朴素混合 +0.66 dB；不重投影则 **−1.36 dB**
  - [x] 学习式时域模型 + 递归历史缓冲 + 遮挡 rejection 掩码（§8.7–8.9；深度拒绝已在
        真实平移序列上验证）
  - [ ] 时域化的误差信号（见 §8.3③），替代当前的空间误差图
  - [ ] depth / motion 等其余 buffer 输入（Mob-FGSR 只用颜色+深度+运动矢量）
  - [ ] 部署路线：离线训练 + 运行时 LUT 查表，或极低比特量化（见 §8.3⑤）
  - [ ] LPIPS；移动端真机（能耗/发热）
- [ ] **M4 — 联合优化（论文核心）**
  - [x] 首个切片：等预算下 uniform vs 屏幕空间误差分配（§7.10）——**负结果**：
        单物体上两种分配退化为同一个 cut；深度排序行上 uniform 仍高 0.56 dB，
        且 38.5 dB 时 tiny 网络只有 +0.05 dB，排序没有被重建改变
  - [x] 低预算（20–30%）下的「分配 × 重建」交互：质量门下限处两种分配再次退化为同一
        cut；26.44% 时历史对 PSNR 为 −0.12（SSIM +0.0035），未发现正向交互
  - [ ] 运动感知的几何预算（静态/慢速/快速运动）与动态策略
  - 由「神经重建能力 + 预计视觉损失」反推几何预算
  - 与 Baseline 1 / 2 对比实验，产出论文
- [ ] **M5 — 移动端落地**
  - Android / Vulkan 后端打通与真机实测
  - 功耗与发热评估

---

### 7.1 M2 首个切片结果

**代码**：`libs/manymesh/`（纯 CPU 算法库）+ `tools/mmgeo/`（命令行工具 + 说明见
`tools/mmgeo/README.md`）。全部构建在仓库已 vendored 的 **meshoptimizer 0.18** 之上
（`meshopt_buildMeshlets` / `meshopt_computeMeshletBounds` / `meshopt_simplify` /
`meshopt_simplifyScale`），**未引入任何新依赖**。

**测试模型**：Stanford Asian Dragon —— 3,609,600 顶点 / 7,219,045 三角面，
包围盒 201.7 × 112.0 × 134.2。

**实测耗时**（Intel 12 代 20 线程，Release）：

| 阶段 | 耗时 |
|-|-|
| 加载 PLY | 4.5 s |
| cluster 化（56,399 个 cluster） | 9.1 s |
| 逐 cluster LOD（5 级） | 14.0 s |
| 选择 + 错误图光栅化 | < 1 s |
| **合计** | **14.8 s** |

**误差对比（同一模型，5 级，比例 0.7）**

每一级保留的面数比例都是 `ratio^L`，所以**同一 level 索引下的对比是公平的**。
取 level 3（各配置都保留约 34% 面数）：

| 配置 | 单元数 | 面数 | 加权平均误差 | 最大误差 |
|-|-|-|-|-|
| 逐 cluster（不分组） | 56,399 | 2,374,748 | 0.013533 | 0.255045 |
| 8 个一组 | 7,050 | 2,468,995 | 0.009080 | 0.175334 |
| 32 个一组 | 1,763 | 2,474,497 | 0.007927 | 0.031153 |
| 64 个一组 | 882 | 2,474,495 | 0.007702 | 0.024651 |
| 全局链（≈ Baseline 2） | 1 | 2,476,053 | ——（单一全局界） | **0.012313** |

> **结论一：逐 cluster 独立简化的代价确实是结构性的。** 即便取**平均**误差
> （0.0135），也已超过全局链的**最差**误差（0.0123）——平均胜过别人的最坏值，
> 说明差距不是统计噪声。根因是边界被锁死：每个 cluster 只能在自己那一小片里做 QEM，
> 误差无法跨 cluster 重新分配。
>
> **结论二：分组（cluster group）能单调收回大部分差距。** 从 1 → 64 个一组，
> 加权平均误差 0.01353 → 0.00770（**降低 43%**，随组大小单调下降），
> 最大误差从 0.255 降到 0.025。做法是把简化单元从「单个 cluster」变成「相邻 cluster
> 组成的一组」，于是边界锁只作用于**组的**外边界，组内成员的共享边成为内部边、
> 可以自由塌缩。实现上只是 `groupClusters()` 一层——因为「组」在数据结构上就是
> 一个更大的 cluster，下游全部代码原样复用。
>
> **结论三：全局链仍最优。** 在唯一可直接比较的「最大误差」上，链 0.0123 仍优于
> 组 64 的 0.0247。分组缩小了差距但没消除——组的外边界依然锁死，而全局链处处可以
> 自由移动边界。这给后续留出了明确空间（层次化 cluster 组 / 多级 DAG）。

> **方法学备注：** 对比误差时有一个坑——`meshopt_simplify` 的 `target_error` 是
> **相对传入顶点缓冲的尺度**的。若不换算，同一个「1%」对小组和大组意味着完全不同的
> 绝对形变，误差上限会随单元大小变化并主导结果，实验就失去可比性。实现里已把它
> 统一换算到世界空间（见 `Simplifier.cpp` 的 `simplifyClusterInto`）。

> **另一个观察：** 对这个过采样严重的扫描模型，屏幕空间预算是个**很弱**的杠杆——
> 从 2.0 px 收紧 20 倍到 0.1 px，绘制面数只从 27.4% 升到 36.5%（大部分 cluster
> 早已处于自己最粗的一级）。这恰好印证 ManyMesh 的前提：**扫描模型的面数远超
> 视觉需要**，真正的瓶颈在几何处理开销而非视觉质量。

#### 7.1.1 属性接缝修复与视觉验收

初版只按位置做 QEM，导入器在 UV/法线 seam 处复制的顶点会被当成普通内部顶点，
于是 cluster 可以跨接缝塌缩。球体降到约 25% 时出现黑色三角洞（PSNR 30.75 dB）；
修复后同样约 25% 无洞，PSNR 37.57 dB。

现在的做法是：`clusterize()` 先按共享索引求连通分量，把接缝拆成独立 chart，再逐 chart
建 meshlet；`groupClusters()` 不再按输出顺序取连续 cluster，而是只沿共享顶点做邻接生长，
因此组不会跨属性接缝或跨不连通分量。

用同一机位、同一 lit 材质（`aiDefaultMat.filamat`）、960×720 重拍并比对：

| 模型 | 保留面数 | PSNR | SSIM | 视觉结论 |
|-|-|-|-|-|
| Stanford dragon | 34.2% | 35.19 dB | 0.96124 | 无破洞；鳞片和角略变软 |
| Sphere | 22.4% | 37.32 dB | 0.99163 | 轮廓多边形化；最粗一级有细接缝明暗线，但拓扑闭合 |
| Monkey | 24.1% | 28.06 dB | 0.93454 | 眼、耳、下巴明显变粗；边界边数量与原模一致 |
| Torus | 33.9% | 37.06 dB | 0.99149 | 明显多边形化，无裂缝 |
| Cloth | 57.5% | 44.27 dB | 0.99709 | 该视角下几乎无差别 |
| Shapes | 20.4% | 63.10 dB | 0.99995 | 地面与小球完整 |

拓扑核对：sphere/torus 的简化结果没有新增边界边；monkey 仍有 168 条边界边，与原始 OBJ
完全相同，属于原模型自带的开口，不是减面造成的裂缝。

仍未解决：每面材质/子网格 ID 没有随简化结果保留，且 QEM 仍只使用位置误差；这两点会
影响生产资产与贴图正确性，但不属于“把几何撕开”。

---

### 7.2 M1 首个切片结果：渲染与画质基线

要判断「用几何换画质」划不划算，必须有办法**渲染出图并量化画质**。本仓库此前只有
`tools/diffimg` 这类容差比较（回答"变没变"），能回答"降了多少"的 PSNR/SSIM/LPIPS
一个都没有。

**新增**：

- `samples/mm_bench` —— 离屏渲染 harness。固定相机、材质、光照、曝光，**不绘制任何 UI**，
  输出 PNG 并报告 GPU 帧时（median / p99 / max）。
- `tools/mmmetrics/compare.py` —— PSNR / SSIM /（可选）LPIPS + 差异图。

> **踩到的坑（值得记下来）：** 不要把 view 留在 Filament 的 camera manipulator 上。
> manipulator 的投影来自窗口事件，而离屏渲染永远不会有窗口事件，结果是**整个场景什么都
> 不画**——不报错，只是一帧空白。必须自己 `Engine::createCamera()` 再
> `View::setCamera()`。`samples/hellotriangle` 是这么做的；`material_sandbox` 不是，
> 所以它的 headless 截图里只有 ImGui 面板、没有模型。

**实测**（Stanford Asian Dragon → 全局链 LOD；1280×720；Intel Iris Xe；OpenGL；
**6 个均匀分布的方位角视角**，一次性加载、逐视角渲染）：

| 面数 | 占原始 | GPU 帧时 (中位) | PSNR 中位 | PSNR 最低 | PSNR 最高 | SSIM 中位 | SSIM 最低 |
|-|-|-|-|-|-|-|-|
| 7,219,045 | 100% | 41.35 ms | —— | —— | —— | —— | —— |
| 5,053,330 | 70% | 28.36 ms | 39.12 dB | 35.69 | 44.39 | 0.9934 | 0.9773 |
| 3,537,268 | 49% | 20.71 ms | 36.40 dB | 31.42 | 41.05 | 0.9850 | 0.9570 |
| 2,476,053 | 34% | 15.26 ms | 35.36 dB | 31.31 | 39.22 | 0.9831 | 0.9554 |
| 1,733,244 | 24% | 10.89 ms | 34.50 dB | 30.92 | 38.58 | 0.9813 | 0.9526 |

**观察：**

1. **单视角会严重误导，画质必须以分布报告。** 同一个模型、同一级 LOD，仅换视角，
   PSNR 就能差 **7.7 dB**（24% 那档：30.92 ~ 38.58 dB）。我们最初随手选的那个视角
   恰好接近**最差**情况，比中位低 3.6 dB。**任何只报单一视角的 LOD 画质对比都不可信**，
   这也解释了为什么文献里同类数字常常对不上。
2. **降到 24% 面数，GPU 时间省掉 74%**（41.4 → 10.9 ms），中位画质代价约 4.6 dB PSNR、
   0.012 SSIM。这是 Baseline 2（传统 LOD）的第一组真实数据。
3. **画质损失不均匀，存在"拐点"**：70% → 49% 中位掉了 2.7 dB，而 49% → 24% 只再掉
   1.9 dB。结合 §7.1 的结论（扫描模型过采样严重），说明「几何预算」应按误差曲线
   而非面数比例来分配。
4. **差异集中在边缘**：70% 那档有 **88.2% 的像素逐位相同**，较大差异（≥8 个 8-bit 级）
   **97.8% 落在边缘上**。这正是 M3 神经重建该发力的位置，也为
   「Geometry Error Map 应加权边缘区域」提供了直接依据。

**尚未做**：LPIPS（需 `pip install lpips`，torch 已就绪）；移动端真机数据（本机是桌面
核显，功耗/发热无法代表手机）；多视角统计（目前是单一固定视角）。

---

### 7.3 M3 首个切片：神经重建与「误差图是否有用」的检验

**目标**：ManyMesh 的核心新意是那张 **Geometry Error Map**——告诉网络"哪些像素的几何是错的"。
这一节就是检验它到底有没有用。

**代码**：`tools/mmtrain/train.py`。数据由前面几步生成：同一批相机下渲染两遍
（全模 = target，第 4 级 cluster 化网格 = 输入），外加 mmgeo 为该视角投影出的误差图。
16 个视角，12 训练 / 4 验证。模型都是几万到十几万参数的小网络，CPU 训练。

**两种任务设定：**

- **scale 1（纯几何）**：640×360 粗几何 → 640×360 精几何。分辨率不变，误差只来自几何，
  这是 ManyMesh 核心主张最干净的检验。
- **scale 2（方案 §6 的真实形态）**：320×180 粗几何 → 640×360 精几何，
  几何误差与分辨率损失叠加。

**结果（PSNR 为 4 个验证视角的中位；delta 为逐视角配对比较）：**

| 方法 | scale 1 | scale 2 |
|-|-|-|
| 粗几何/双三次（下界） | 31.48 dB | 30.59 dB |
| tiny（本方案） | **33.36** | **31.57** |
| unet（小 U-Net） | 33.23 | 31.67 |
| espcn (CVPR'16) | 31.90 | 29.56 |
| fsrcnn (ECCV'16) | 32.07 | 28.69 |

| 方法 | 误差图增益 (scale 1) | 误差图增益 (scale 2) |
|-|-|-|
| tiny | +0.027 dB | +0.067 dB |
| unet | +0.061 dB | +0.116 dB |
| espcn | −0.004 dB | +0.072 dB |
| fsrcnn | +0.129 dB | **−0.193 dB** |

> **结论一（成立）：神经重建本身有效。** 等分辨率下，小网络把粗几何的 31.48 dB 提到
> **33.36 dB（+1.88 dB）**；半分辨率下比双三次高 **+0.98 dB**。M3 的前提站得住。

> **结论二（负面结果，必须如实记录）：目前的 Geometry Error Map 没有带来有意义的收益。**
> 增益在 **−0.19 ~ +0.13 dB** 之间，**符号随模型和任务翻转**，量级远低于感知阈值。
> 逐视角配对看，有些组合（unet/fsrcnn 在 scale 1）四个视角同号，但幅度依旧可以忽略。

> **对负面结果的诊断（这是下一步的依据）：**
> 1. **误差图几乎只是个轮廓掩码。** 覆盖区中位值仅 15/255，因为它按像素预算归一化，
>    而该网格的误差远在预算之下。而轮廓在哪，RGB 输入本来就看得见——信息高度冗余。
> 2. **没有足够的误差可利用。** 第 4 级 cluster 网格本身就有 31.5 dB，网络能修的很少，
>    误差图自然也无从指引。真正需要误差图的是**更激进的压缩**。
> 3. **数据量太小。** 12 个视角、1500 次迭代，不足以让网络学会利用额外的输入通道。
>
> **后续动作**：把压缩推到误差图真正饱和的档位；按视角归一化误差图以获得动态范围；
> 视角数提到数十量级；或改变形式——用 cluster 级的条件编码替代屏幕空间图像。

**后续实验（架构、数据、损失、以及误差图本身）**

围绕「误差图为什么不起作用」查了相关文献并逐条验证。参考文献给的配方是
**Kernel-Predicting CNN（Bako et al., SIGGRAPH 2017）**：网络不直接出像素，而是预测
每像素的空间滤波核作用到颜色缓冲上，辅助特征由此获得**机制性**作用。另一类是
**多分支 / 高分辨率辅助特征**（CGF 2024 的联合降噪+超分）。

| 实验 | 结果 | 结论 |
|-|-|-|
| `tiny`（残差 CNN） vs `kpn`（核预测） | 33.37 vs **31.48** | **架构不是瓶颈**；核预测只能*滤波*，无法*合成*几何细节 |
| `unet`（17.6 万参数） vs `tiny`（2.8 万） | 33.23 vs 33.37 | **容量不是瓶颈** |
| 1500 → 6000 次迭代 | 33.37 → 33.42 | **训练量不是瓶颈**，已收敛 |
| 误差图逐视角归一化 | +0.04 dB | 无效 |
| 边缘（梯度）损失 w=2.0 | **33.37 → 33.50** | **有效**：L1 的最优解偏模糊，会抹掉边缘 |

**误差图本身的诊断**（这是关键）：

- 它**确实预测误差**：**99.3% 的图像误差落在它的覆盖区内**（区内平均 0.0186、
  区外 0.0000），且取值与误差严重程度单调相关（分位 0.0141 → 0.0235）。
- 但它**与彩色图高度冗余**：这些误差全在边缘上，而边缘在彩色图里本来就看得见，
  所以它只值 **+0.02 ~ +0.04 dB**。

> **对「Geometry Error Map」这一核心新意的诚实结论：** 它是一个**有效但冗余**的信号。
> 它能告诉你误差在哪，而这件事彩色图已经告诉你了。要让条件输入真正有价值，它必须携带
> **彩色图看不到的信息**——例如几何误差的**有符号方向**（真实表面在前还是在后）。
> 但那在运行时不可得（要得到它就得有高模，而那正是我们想省掉的）。
>
> **这反而把 M3 的定位讲清楚了：** 重建的价值来自网络**学到的高频细节先验**，
> 而不是来自条件信号。+2.0 dB 就是先验在起作用。后续重心应该放在**更强的先验**
> （更大的数据、感知/对抗损失），而不是更好的误差图。

> **公平性声明：** ESPCN / FSRCNN 在这里低于双三次，**不代表这些架构差**。它们的原论文
> 用数万张图像训练十万级迭代，而我这里是 12 张图、1500 次迭代——差距来自数据预算，
> 不是架构。表中的它们只能读作"在同等极小预算下"。

---

### 7.4 场景级（地图）测试：能优化多少

前面所有测量都是**单个物件**——镜头里能看到全部几何，选择机制除了"远近"没有别的东西
可利用。真实关卡不是这样：大部分几何在视野外或很远。为此补了三件事：

1. **选择加入视锥剔除**。此前相机背后的 cluster 因为深度被 clamp 到近平面、屏幕误差显得
   极大，会被判为 level 0，导致场景的面数被严重虚高。现在用球-视锥测试标出渲染器本就会
   剔除的 cluster，单独计数。
2. **mmgeo 显式指定相机时也按场景设置 `near/far`**。默认 `far=1000` 会把 1000 单位以外的
   整片场景静默剔除掉。
3. **`tools/mmscene`** 用拼接生成大地图（可选加地面）。公开的场景库（Bistro / San Miguel /
   Powerplant / Sponza）每个几百 MB 到 1GB，而本机链路慢、还要保持可用，所以这里的大场景
   是**合成的**——比真实扫描关卡弱，文档里已注明。

**测量（合成地图：5×5 个 41.6 万面网格 + 50 万面地面 = 10,903,075 面，
2100 × 123 × 2100；地面高度视角；640×360；Intel Iris Xe）：**

| 指标 | 数值 |
|-|-|
| 视锥剔除 | 49.0% |
| **实际绘制** | **1,333,651（场景的 12.2%，可见几何的 24.0%）** |
| GPU 帧时 | ~52.8 ms → **8.82 ms（约 6×）** |
| 画质（vs 全细节） | PSNR **30.29 dB** / SSIM 0.9297，94.0% 像素完全相同 |

> **结论：只画 1/8 的三角形，换来约 6× 的提速**（各次测量 4.7~7.1×），逼近 8.2× 的
> 面数削减比——**帧时基本正比于三角形数**。这与 §7.5 的结论一致。
>
> 画质代价是 30.29 dB / SSIM 0.9297，94.0% 的像素逐位相同，且模型占画面 38%——
> 比单物件测试（35.7 dB）低，因为误差铺在一大片近处表面上，而不是集中在几条轮廓线上。

**注**：这里最初的数字（1.59×）是错的，根因见 §7.5——写出的低模把视野外几何按全细节
带了进去。更正后为约 6×。

---

### 7.5 瓶颈量化：一次被 RenderDoc 抓出来的测量错误

§7.4 最初测出的「只画 1/8 三角形只换来 1.59×」是**错的**，根因是一个 bug。
这一节记录更正后的结论，以及错误的发现过程——它比结论本身更有价值。

**用 RenderDoc 定位。** RenderDoc v1.46 便携版装在 `D:\RenderDoc\`。给它接上脚本化抓帧
需要三步（`renderdoccmd` 没有"抓第 N 帧"的参数，所以要应用内触发）：

1. `samples/mm_bench` 加了 `--capture-frame N`：进程内 `GetModuleHandle("renderdoc.dll")`
   取到 API 后 `TriggerCapture()`。头文件 `renderdoc_app.h` 用 `__has_include` 保护，
   没有它时照常编译。
2. `renderdoccmd capture -c <模板> <exe> <args>` 抓帧。**两个坑**：RenderDoc 会改工作目录
   （网格要用绝对路径），而且 Git Bash 会改写绝对路径（需要 `MSYS_NO_PATHCONV=1`）。
3. `renderdoccmd convert -i rdc -c zip.xml` 把捕获转成 **XML**，于是可以脚本化解析
   （Python 绑定不在便携包里，PyPI 上也没有 `renderdoc` 包）。

**XML 立刻暴露了问题**：HR 的 draw 提交 10,903,075 个三角形（等于地图面数，正确），
但 LR 的 draw 提交了 **6,677,900** 个——而 mmgeo 报告"只画 1,333,651"。

**Bug**：被视锥剔除的 cluster 在 `selectImpl` 里走 `continue`，跳过了 `levelPerCluster[c]`
的赋值，保持默认值 **level 0（全细节）**。`selectedTriangles` 正确地没统计它们，
但 `gatherSelection()` 把它们按全细节写进了 `selected.ply`。
于是 6,677,900 = 1,333,651（可见）+ 5,344,249（被剔除），**渲染的是 10.9M vs 6.68M
（1.63× 削减），不是 8×**。视野外几何只花时间、不进画面，所以画质数据一直是准的，
只有性能数据全错。

修复后重新测量（3 次重复，640×360）：

| 配置 | 实测 |
|-|-|
| HR（10,903,075 面） | 41.2 / 52.8 / 62.5 ms（中位 52.8，波动 ±20%） |
| LR（1,333,651 面 = 12.2%） | **8.82 / 8.83 / 8.83 ms**（极稳） |
| **加速比** | **约 6×**（各次 4.7~7.1×） |

> **更正后的结论：帧时基本正比于三角形数。** 三角形降到 12.2%（8.2×），帧时约降 6×。
> 之前所谓"次线性收益""瓶颈不在几何"的说法**是测量错误导致的，不成立**。
> 顺带，之前那条"几何受限还是片元受限"的分析也随之作废。

仍然成立的旁证：

- **分辨率几乎不影响帧时**：像素翻 4 倍（360p→720p），LR 只慢 4.5%、HR 只慢 1%。
  所以这一帧不是片元受限。
- **阴影 pass 不是成本来源**：整图开/关阴影无差异。
- **没有大的固定开销**：渲染一个不在视野内的 1.5 万面模型（等于空帧）只要 0.33 ms。

> **教训**：性能结论必须建立在**验证过的**计数之上。这里的错误不是渲染问题，而是
> "我以为我渲染了多少"和"我实际提交了多少"之间的偏差。抓一次帧、把 draw 的
> 三角形数打出来，一眼就能发现——**这就是装 RenderDoc 的价值**。

> **测量环境警告**：本机核显与远程桌面会话共享。LR 三次重复只差 0.1%，HR 波动达 ±20%，
> 所以重负载下的绝对毫秒数不可信，可比的是同期测得的**比值**。

---

### 7.6 几何层第二轮：DAG、质量门、运行时选层与近细远粗

这一轮把 §7.1 留下的「层次化 DAG / 属性 / 质量门 / 编辑器调节」补成了可运行版本。

**结构**

- 每个 cluster 有自己的 LOD 链，组父节点把最多 8 个子节点合并后再简化，因此一个 view
  可以在不同子树里选不同层级，而不是整模型只切一个 LOD。
- 节点保留 `materialId` / `submeshId`；渲染时按 `(material, submesh)` 拆 primitive，
  不再把整个选择塌成一次 draw。
- normal 和 UV 已进入 attribute QEM 的 collapse cost，而不只是事后统计。

**质量门（默认开启）**

每个候选层必须同时满足：边界边集合与基元完全一致、非流形边不增加、无重复/退化/翻转
三角形、最小三角形质量不低于阈值、位置误差不超过 `targetError × mesh scale`。
最后一条是这轮新增的：此前的门只能看见拓扑坏了，看不见「拓扑完好但表面被拉出一个坑」。

**视觉回归**（1280×720，同一相机，`--no-shadows`）

| 模型 | 原始面数 | 50% 目标 | 75% 目标 | PSNR / SSIM |
|-|-|-|-|-|
| sphere | 8,064 | 4,032（50.00%） | 1,736（21.53%） | s50: 42.01 dB / 0.99770；s75: 41.18 dB / 0.99632 |
| monkey | 15,744 | 7,872（50.00%） | 5,426（34.46%） | s75: 38.80 dB / 0.99157 |
| torus | 1,152 | 562（48.78%，seam pair） | 同 50% 档 | s50: 30.08 dB / 0.99195 |

> sphere 的 75% 档只到 21.53%、monkey 只到 34.46%，不是选择器算错，而是更激进的候选被
> 质量门拒绝了。UI 必须显示**实际**面数比例，不能只显示目标值。torus 在加入成对 seam
> collapse 之前卡在 66.32%；现在同一条质量门下可到 48.78%，焊接后边界为 0。

> **一个重要的视觉陷阱**：早期 sphere 截图上看到的「右侧缺口」不是几何洞。把同一份
> 选择导出后检查，所有顶点半径都是 0.500000，边使用次数全为 2（闭合），法线全部径向。
> 缺口来自低模阴影贴图的自阴影；用 `--no-shadows` 后消失。因此几何回归必须同时看
> 「关阴影的同机位截图」和拓扑/位置指标，不能把渲染伪影记到算法头上。

**近细远粗**

`selectLodGraph` 用 `accumulatedError / depth` 计算每个节点的屏幕像素误差；同一个像素阈值
下，近处节点会更晚被父节点替换。mm_bench 已提供：

```text
--distance-lod --screen-error 2.0
```

以及 UI 里的 `Distance-aware (near fine, far coarse)` 开关和 `Screen error` 滑杆；
开关也可以直接按 `D` 键切换，便于在同一机位下做开/关 A/B 对比。
实测 monkey 在 2 px 下：近相机 8,738 面（55.50%），远相机 6,224 面（39.53%）。
同一 2 px 阈值下，monkey 为 42.36 dB / 0.99526，torus 为 49.40 dB / 0.99944；
它比固定 savings 更接近原始画面，因为误差只花在真正需要的屏幕区域。

> **屏幕误差深度口径修正（本轮）**：上面的 `depth` 必须取包围球的**最近点**
> （`dot(center - eye, forward) - radius`），而不是球心深度。近距离大 cluster 的球心
> 可能比表面远得多，用球心会低估误差、把本该保留的细节点提前换成父节点，正好伤害
> “近细远粗”。`GeometryError` 原本就是最近点口径，但 `LodGraph`、`mmgpu` 的 host
> reference 和 GPU `screenError()` 仍是球心口径；本轮统一到
> `screenSpaceErrorForSphere()` / `ScreenErrorProjection`，并 clamp 到近平面。
> `test_manymesh` 新增 `ScreenSpaceErrorForSphereUsesNearestDepth` 回归。

**运行时可行性**

- DAG 构建、attribute QEM、质量门都是离线/编辑器侧，不需要每帧重跑。
- 运行时只做一次 DAG cut：`selectLodGraphCut` 只输出选中的节点，不拼接索引/材质数组。
  在 588 节点的 monkey DAG 上，CPU 单线程实测 **0.0031 ms/次**。
- 需要完整索引数组的编辑器路径 `selectLodGraph` 为 0.115~0.253 ms/次（monkey，距离模式），
  0.657~0.892 ms/次（savings 模式，含 32 次阈值二分和预算内细化）。两者都远低于 16.7 ms。
- `mm_bench` 的 UI 调参路径也已改成生产形状：所有 DAG 节点的索引一次性打包进一个静态
  index buffer（`flattenLodGraph` 的布局），renderable 只创建一次；每次 cut 变化只调用
  `RenderableManager::setGeometryAt` 更新预建 primitive 的区间，不再重新打包或上传索引。
  `--show-original` 复用叶子节点集合，因此仍能逐三角形还原原始网格。

**已完成（独立 Vulkan 原型）**：`tools/mmgpu/` 用真实 Vulkan 1.0 跑通了 compute shader
DAG cut、`vkCmdDrawIndexedIndirect` 和 depth-tested visibility buffer。GPU cut 与 CPU
reference 在 torus/monkey 上节点集合和三角形数完全一致，visibility 深度无差异。它不依赖
Filament 公共 `RenderableManager`，因此证明的是算法与 GPU 数据布局可行，而不是 Filament
后端集成已经完成。

**当前状态**：`mm_bench --gpu-cut` 已通过 Filament 私有 `DriverApi` 在 OpenGL 和 Vulkan
后端提交 compute cut，并用 `assembleLodSelection()` 复用 CPU 的跨节点去重与材质装配；
torus 两端实测均为 `nodeMismatch=0 / triangleMismatch=0`（9 nodes、858 triangles）。
首次 dispatch 约 OpenGL **779 ms**、Vulkan **645 ms**（均含 shader 编译），CPU 同一 cut
约 **0.02–0.05 ms**。GLSL 450 与 GLSL ES 3.10 cut shader、`GpuLodCutParams`、计数器布局
和相机屏幕误差数学已下沉到 `libs/manymesh`，`mm_bench` 与 backend 回归共用同一份实现，
避免 sample 和测试各维护一份 shader。`compute_test` 为 Vulkan **7/7**、OpenGL
**6 passed / 1 skipped**；其中 GLES 用例只验证 shader 能编译成 SPIR-V，尚未覆盖 Android
真机驱动。当前路径仍同步回读选择结果并在 CPU 重建几何，**不是**常驻 GPU-driven 路径；
默认构建未启用 Vulkan。**仍未完成**：Filament Vulkan backend 侧的常驻 compute/indirect
路径、真实 GPU 侧 cut compaction 接入正式渲染器，以及 Android/iOS 真机网络与 GPU 验证。
跨 UV chart 的 seam 简化已在本轮补齐，见 §7.8。
`AsyncLodStreamingCache` 提供不阻塞调用线程的预取、可插拔 fetcher，以及直接接收
`(byteOffset, byteCount)` 原始字节的 transport 接口。Windows 上的
`HttpByteRangeFetcher` 已经用 WinHTTP 接通 HTTP/HTTPS Range 请求（本地回环 + `mm_bench
--stream-url` 端到端验证通过，0 失败页）；Android/iOS/Linux/macOS 默认走 vendored
CivetWeb 的 HTTP Range 实现（本地回环 206 测试通过），缓存与解码层共用同一接口。Filament 的公共 `RenderableManager` 仍没有提交 indirect draw
的入口；当前真实 GPU 路径位于独立工具中，生产集成需要改 Vulkan backend 或换自定义渲染器。

**本轮性能优化**

- `AttributeSimplifier` 的候选塌缩原先在每次评估里创建 `std::set` / `std::map`。现在改成
  预留容量的小向量、排序后的边表与哈希集合；初始边只评估一次（同一条内部边不再被两个
  相邻三角形各推一遍）。
- `selectLodGraphAtRatio` 的 32 次阈值二分共用一份 `NodeMetrics`（屏幕误差与视锥剔除
  结果），不再每轮重复投影。
- `mm_bench` 的滑杆拖动期间只更新 cut 与统计，松开滑杆后才上传索引；上传目标是一个
  持久 index buffer，不再销毁/重建 renderable。
- `simplifyClusterInto` 的 `localPositions` / `localToGlobal` / `localIndices` /
  `destination` 改为跨单元复用的 scratch，按 unit 只做 `clear/resize`。
- **extended-mesh 复用（2026-10 新增）**：`simplifyClusterInto` 的
  `extendedMesh = mesh` 会为每个 cluster/group 复制整张共享网格，质量门却只读取
  positions/normals/UVs/AO。现在 `SimplifyScratch` 用 `meshCacheEpoch` 在同一个构建批次内
  复用 base 顶点快照，只追加 generated 尾部；`SimplifyProfile` 新增
  `extendedMeshSeconds` / `extendedMeshCopies`，`mmgeo` 会打印
  `extended-mesh: ... copies ...`。同一 cloth 命令（74,976 三角形、9 级、
  `--target-ratio 0.5`）总构建 **21.07s → 18.63s（-11.6%）**，
  `extended-mesh` **3.25s / 2197 copies → 0.28s / 120 copies**，DAG 的
  `1986 nodes / 9 levels / 37488 drawn`、节点索引、误差和拓扑统计逐位不变。
  monkey 同路径保持 `413 nodes / 7124 drawn / worst 20.2738 px`。新增
  `CachedExtendedMeshDoesNotChangeSimplifiedOutput` 回归，覆盖同一 epoch 复用与
  `epoch=0` 重新快照的输出一致性。
- **corner 落点评估优化（2026-10 新增）**：串行 profile 定位到
  `CornerSimplifier` 的 `target` 阶段：cloth 一次 DAG 构建有 1113 万次落点评分，
  49.1s 花在重复的重心坐标、叉积/面积、`acos` 和最近三角形查询上。现在：
  每个落点只算一次 `BarycentricWeights`，`triangleNormalAndQuality()` 用一次叉积同时
  得到法线和质量，最近三角形查询先用两个塌缩端点的距离作上界、再用三角形平面距离作
  `pointTriangleDistance2` 的严格下界，并在表面误差的数学下界已经打不过当前最优时直接
  跳过整圈距离查询。同一 cloth 命令串行总时间
  **101.19s → 85.93s（-15.1%）**，`target` **49.08s → 32.64s（-33.5%）**，
  `evaluate` **63.58s → 49.34s（-22.4%）**，DAG 的
  `1971 nodes / 7 levels / 37488 drawn / worst 8.8090 px`、生成顶点数和拓扑统计逐位
  不变，`.mmb` 的 SHA256 与优化前完全相同。默认并行构建
  **18.63s → 15.81s（-15.1%，多次运行 15.8–16.5s）**，输出仍是
  `1986 nodes / 9 levels / 37488 drawn / worst 7.8916 px`，哈希同样一致。所有剪枝都是数学下界，
  没有放松质量门或改变落点排序。
- `selectionFromCut` 不再排序整个选择：先标记跨节点的共享顶点，只对边界面做哈希去重，
  同时删掉了原先“拼一遍索引再丢弃重建”的重复遍历。
- 屏幕误差路径 `selectLodGraph` 与比例路径统一到同一个 cut 清理函数，距离感知选层也不会
  再输出跨节点重复面。
- `selectionFromCut` 的顶点归属表改成线程局部的代际标记，重复 selection 不再按网格总顶点
  数分配和清零；只触碰当前 cut 实际引用的顶点。
- 流式格式升级到 v3 并写入 `vertexCount`，仍可读取 v2；`AsyncLodStreamingCache` 新增
  `LodGraphCut` 预取重载和原始字节区间 fetcher，缓存查找从扫描 resident map 改为按页表
  二分定位。
- `mm_bench` 的节点索引只上传一次，cut 切换不再重建 index buffer；torus 新路径与旧路径
  同机位截图逐像素一致（PSNR `inf`，SSIM `1.0`）。
- `AsyncLodStreamingCache::request` 会丢弃旧 cut 尚未启动的排队页，已经运行中的 fetch
  允许完成并留在缓存里；快速转动相机不再积累过期页。新增回归测试覆盖该行为。
- 同步/异步 cache 的必需页集合从 `std::set` 改为排序去重的 `std::vector`，每帧规划
  不再为每页分配红黑树节点；LRU 淘汰用二分查找判断“当前 cut 仍需要”。
- 新增 `HttpByteRangeFetcher`：Windows 用 WinHTTP、其余平台用 vendored CivetWeb，
  支持超时、IPv6 和 `Range: bytes=a-b` 校验（WinHTTP 另支持重定向）；`mm_bench --stream-url` 可直接
  从服务器流式加载 `lod_graph.mmb`，`--stream-save` 用来导出同一份文件。
- 质量门里的最近三角形查询从逐顶点扫描全部候选三角形改为 BVH；位置误差与属性误差共用
  同一次最近点查询，不再重复构建和遍历两棵树。对小 unit，候选网格本来就不大，但组父节点
  的简单化会反复调用质量门，收益随 group 大小增长。
- 逐 cluster LOD 链与同一层的独立 group 都改为并行构建。每个 worker 持有自己的 remap
  与 scratch；结果按原始 group 顺序合并，因此节点 ID、children、索引和误差字段保持逐位
  一致，不引入由线程完成顺序决定的 DAG。
- `selectLodGraphAtRatio` 的跨节点重复面哈希表改为线程局部复用；编辑器拖动滑杆时反复
  评估阈值不再为每个 cut 分配新表。
- cloth DAG（74,976 三角形，group 8，5 级，ratio 0.7）从 **37.02s** 降到 **1.93s**；
  其中 BVH/shared-query 后的串行路径仍有 **18.18s**，并行后降到 **1.93s**（约 9.4×）。
  输出仍是 `1915 nodes / 7 levels / 252 roots / 589 leaves`、
  `38098 / 74976 = 50.81%`。并行后的阶段耗时示例：clusterize `0.060s`、leaf setup
  `0.021s`、cluster chains `0.534s`、groups `1.163s`。monkey DAG 从 **3.21s** 降到
  **0.23s**。设置 `MANYMESH_BUILD_THREADS=1` 可强制走串行路径，用于复现与 A/B 对比。
- `test_manymesh` 增至 **44 个**（43 个常规测试 + 1 个需
  `MANYMESH_HTTP_RANGE_TEST_URL` 的网络测试），新增“并行构建逐位确定性”、
  “source + generated 全 cut 压缩”和“4 chart 副本焊接”回归；常规测试全部通过。
- 同机位 960×720 视觉回归（`--no-shadows`，自动取景）：monkey 50% 为
  **7,872 面（50.00%）/ 40.99 dB / 0.99349**，aggressive 为 **6,042 面（38.38%）/
  38.12 dB / 0.99009**；torus 为 **562 / 1,152（48.78%）/ 40.56 dB / 0.99655**。
  diff 图只剩轮廓和法线插值差异，没有穿孔、翻面或新增非流形边。
- **corner 简化剖析与热点清理（2026-10）**：`CornerSimplifyProfile` 现在把 corner 路径的
  `setup / evaluate / topology / target / apply` 分开计时，`topology` 再拆成
  `neighbor / triangles / local-triangles / local-edges`，并通过 `SimplifyProfile`
  聚合到 `mmgeo` 的 cluster/group 两行输出。剖析显示 topology 占 evaluate 的约 80%，
  其中 local-triangle 排序和 local-edge 去重是最大头。
  现在 neighbor、affected、local-triangle 全部改用 thread-local 代际标记去重，不再排序；
  local-edge 只统计被本次塌缩改写的三角形（其余边的 use count 不变），非流形 unit 自动回退
  到完整 two-ring 检查。`MANYMESH_CORNER_FULL_EDGE_CHECK=1` 可强制走完整检查做 A/B，
  三条测试资产在两条路径上输出逐位一致。
  同时修掉了 incidence 列表中**已死亡三角形仍参与 local edge 计数**的问题；这会让一部分
  本来合法的塌缩被误拒，torus 一度能到 30.03%（346 / 1,152）。修复后暴露出同一 source
  corner 在相邻三角形上会被插值到不同 UV（实测最大差 0.04）。旧实现把这种分歧当成拒绝
  条件，torus 因此停在 33.16%；现在默认不再拒绝，而是按 UV cluster 输出多个**同位置**
  的 generated vertex，每个 chart 保留自己的仿射参数化。`--corner-split-uv 0` 只用于
  复现旧的“平均 UV”行为做 A/B，默认值为 1。
  当前默认质量门下的实测是：torus `--target-ratio 0.2` 为 **400 / 1,152 = 34.72%**，
  closed、min quality 0.2869；monkey `--target-ratio 0.3` 为 **4,712 / 15,744 = 29.93%**，
  `--target-ratio 0.2` 为 **4,162 / 15,744 = 26.44%**，
  `boundary 168 / non-manifold 0 / duplicate 0 / flipped 0`。torus 的剩余拒绝是 group
  topology 16 / geometry 1，UV 已不是主要阻塞。旧版 33.16% / 38.00% 的截图和 PSNR 属于
  UV 拒绝门版本，不能当作当前默认结果引用。
  单次 corner 评估从约 **5–10 µs** 降到 **1.5–3.8 µs**；加入下面的塌缩优先级后，
  monkey DAG（7 级）约 **4.5s**，torus 约 **0.30s**。完整检查路径下同机 monkey 为 3.6s，
  说明新路径本身贡献约 13–15%，其余差异来自修复后实际多做的塌缩与层级。
  旧版视觉回归（UV 拒绝门，仅供历史对照；当前数字见上面的同目标 A/B）：
  960×720，`aiDefaultMat`，`--no-shadows`；monkey eye
  `(0,-0.016,3.25)`，torus eye `(0,0,3.2)`，target 均为原点）：
  monkey 44.99% 为 **37.80 dB / 0.98573**，38.00% 为 **37.37 dB / 0.98135**；
  torus 33.16% 为 **38.94 dB / 0.99451**（cloth 本轮未重跑）。逐图检查无穿孔、无翻面、
  无新增边界，也没有可见的 UV 拉花。
- **corner 塌缩优先级：表面偏差 + 属性 + 最差三角形质量（2026-10-19）**：
  `CornerSimplifier` 之前按 QEM `cost` 从队列取边；placement 评分虽然看局部表面偏差，
  但队列仍会先做“quadric 便宜、局部表面却更差”的塌缩。现在队列直接使用 placement
  评分：`surfaceError/edgeLength + 0.25·uv/limit + 0.1·normal/limit +
  0.1·barycentricOutside + 0.25·(1-minTriangleQuality) + 1e-6·QEM`。质量项权重 0.25
  是 torus/monkey 扫描的平衡点：0.10 在 monkey 同目标下多保留约 4% 三角形，0.50 会把
  DAG 压浅并退化到 7,518 面。质量门、焊接 boundary 集合和 chart UV 拆分都没有放宽。
  同目标：torus `--target-ratio 0.2` **550 → 400（47.74% → 34.72%）**，monkey
  `--target-ratio 0.3` **7,124 → 6,244（45.25% → 39.66%）**，拓扑缺陷仍全 0。
  同面数（更公平）：monkey 新 7,084 面 vs 旧 7,124 面，960×720 同机位、`--no-shadows`：
  **35.50 dB / 0.98590 vs 34.61 dB / 0.98443**，平均绝对差 0.002235 vs 0.002421；
  torus 新 562 vs 旧 550 为 37.22 / 0.99646 vs 37.58 / 0.99554（PSNR 略低，但 SSIM
  与平均误差更好）。代价是 monkey DAG 构建约 3.1s → 4.5s，运行时 cut 仍为 0.0018 ms。
  cut 顶点同步下降：monkey 7,867 → 7,402，torus 625 → 562，移动端上传量更小。
  同机位对照图：`out/ab-monkey-priority-montage.png`、`out/ab-torus-priority-montage.png`。
- **属性误差 chart 选择（2026-10-19，本轮新增）**：`measureCandidateErrors()` 原先只为每个
  源顶点取一个位置最近的三角形，再在这个三角形上插值 normal/UV。UV/normal seam 的同位置
  副本会让 BVH 先命中另一张 chart，于是把本来匹配的源顶点误报成 45–72° 法线误差或
  0.55–0.68 的 UV 误差。现在位置误差仍取真正最近三角形，但属性误差会在
  `bestDistance + tinyTieTolerance` 内的候选三角形中，选择插值 normal/UV 最接近源顶点的
  那个；质量门阈值、拓扑检查、boundary 集合都没有改变。
  monkey `--target-ratio 0.3` **6,244（39.66%）→ 4,712（29.93%）**，
  `--target-ratio 0.2` **→ 4,162（26.44%）**；group 属性拒绝 **80 → 12**，
  `--quality-debug 1` 同参数构建约 **4.47s → 3.23s**。剩余 12 次属性拒绝仍有
  max normal 45–72°、mean 1–5° 的离群点；本轮不为它们放宽门槛，后续需要区分
  generated-vertex 参考点误差与真实 seam 损失。
  960×720、同机位、`--no-shadows`、同一高模参考下，同 6,244 面新路径为
  **27.10 dB / 0.97167 SSIM**，修复前同面数为 **25.24 dB / 0.92891**；26.44% 档目视
  有明显面片感，但无孔洞、无翻面、无新增边界。对照图在
  `out/ab-monkey-attrfix-ref.png`、`out/ab-monkey-attrfix-4162.png`、
  `out/ab-monkey-attrfix-6244.png`。新增
  `AttributeMetricsSelectTheSourceChartAtADuplicatePosition` 回归，验证两个同位置 chart
  副本各自匹配自己的 normal/UV。
- **共享网格 scratch 与焊接拓扑门（2026-10-18）**：corner 候选原先每次 attempt 都执行
  `Mesh extended = mesh`，把整个共享网格（cloth 为 38k 源顶点 + 40k generated）复制一遍，
  只为了追加少量 generated 顶点。现在 `SimplifyScratch` 每个 worker 保存一份 base mesh，
  每次简化调用只复制一次，attempt 只重写 generated 尾部。另一个热点是焊接拓扑门：
  `measureWeldedTopologyImpl` / `preservesWeldedBoundaries` 原先为每个候选分配
  模型总顶点数的 `vector` 和 `std::map`；现在只哈希当前 unit 实际引用的顶点，边界集合改用
  排序后的 `uint64_t` 数组。
  同一命令（cloth 74,976 三角形，`--mode dag --levels 7 --cluster-tris 128`）：
  DAG 构建 **8.42s → 6.63s（-21.3%）**，cluster chains **2.82s → 2.11s**，
  groups **5.07s → 4.19s**；`1989 nodes / 8 levels / 272 roots / 589 leaves`、
  cut `37488 / 74976 = 50.00%`、boundary `500`、non-manifold/duplicate/flipped `0`、
  以及 `cut vertices 30953` 全部不变。monkey 同机位截图与优化前逐像素一致
  （PSNR `inf`，SSIM `1.0`），`test_manymesh` 仍为 **57 passed + 1 skipped**。
  这一步是 CPU 构建优化，不需要 RenderDoc；GPU 原型阶段再用 RenderDoc 分析 dispatch /
  visibility pass 更合适。

**下一批可优化点**：Filament 应用层公共 compute/indirect/storage-buffer 入口、持久 GPU
buffer 与 GPU 侧 cut compaction；把 mmgpu 的 visibility buffer 接进正式渲染器；
移动端真机 HTTP/HTTPS 验证。CPU 侧 source + generated 顶点已按 cut 实际引用压缩
（§10.1）；三份以上同位置副本由 corner 焊接路径处理，并有 4-copy 回归测试（§7.8）。

### 7.7 真实 Vulkan 原型：GPU cut、indirect draw 与 visibility buffer

`tools/mmgpu/` 是独立的 Vulkan 1.0 工具。它从 OBJ 构建 ManyMesh DAG，把 `GpuLodNode` 作为
std430 storage buffer 上传：

1. compute shader 每个 DAG 节点一个 invocation，沿 parent 链判断祖先是否被剔除、是否已经
   足够粗，再检查节点自身误差，输出与 `selectLodGraphCut` 相同的非重叠 cut；
2. 同一个 dispatch 用 atomic range reservation 把选中节点的 index 复制进紧凑 index buffer，
   并直接写 `VkDrawIndexedIndirectCommand`；`firstIndex` 指向 GPU 分配的紧凑范围，
   `firstInstance` 直接携带 DAG node id；
3. 三轮 GPU 顶点压缩：第一轮按 index 引用标记 source 顶点，第二轮给标记顶点分配密集 id
   并 gather 位置，第三轮把紧凑 index buffer 重写成新 id；三轮都没有跨 invocation 自旋，
   避免移动 GPU 上的 forward-progress 风险；
4. 一次 `vkCmdDrawIndexedIndirect` 消费 GPU 生成的 vertex/index/indirect buffer；
5. 片元写入两张 `R32_UINT`：cluster ID 和 triangle ID，同时用 `D32_SFLOAT` 做真实深度测试；
6. 回读后与 CPU reference 按像素比较。

本机（Intel Iris Xe）实测：

| 场景 | CPU cut | GPU cut | GPU 紧凑顶点 | 可见像素 | 节点一致 | 三角形一致 | 深度差异 |
|---|---:|---:|---:|---:|---:|---:|---:|
| torus, 640x360, 2 px | 9 nodes / 1,062 tris | 9 / 1,062 | 592 / 637 | 23,700 | 99.99% | 99.93% | 0 |
| monkey, 640x360, 2 px | 169 nodes / 11,136 tris | 169 / 11,136 | 7,604 / 9,908 | 27,648 | 99.98% | 99.93% | 0 |
| cloth, 640x360, 2 px | 435 nodes / 36,068 tris | 435 / 36,068 | 18,637 / 38,091 | 32,878 | 99.89% | 99.75% | 0 |

monkey 在 0.5/1/2/4/8 px 五档阈值下，GPU 与 CPU 的节点集合、三角形数和剔除计数全部一致；
完全背对相机时两者都报告 1,152 个剔除三角形和 0 个可见像素。少于 1% 的 triangle-id
差异集中在共享边上的光栅化 tie-break，node id 与深度保持一致。

视觉检查没有发现破面、洞或轮廓损坏。CPU/GPU/diff visibility 对照图位于
`out/mmgpu-final-torus/` 与 `out/mmgpu-final-monkey/`（构建产物，不提交）。

GPU 路径的 cut 压缩已经完整：compute shader 直接产出紧凑 index、indirect command 和紧凑
顶点位置，draw 不再回读 CPU 再重建任何 buffer。三个模型上 GPU 紧凑 index 与 CPU
`compactLodSelection` 逐元素一致（排序后比较），indirect command 数等于选中节点数。

**接进 Filament 的具体缺口**：后端已经补上 compute 支持——`VulkanDriver::dispatchCompute`
有真实实现，`VulkanProgram` 增加了 compute shader 槽，compute pipeline layout 与
storage-buffer descriptor 也走同一套 descriptor set；`NoopDriver`、`OpenGLDriver` 和
`WebGPUDriver` 同样实现了 dispatch，`DriverAPI` 也已补上 `drawIndexedIndirect`
（Vulkan `vkCmdDrawIndexedIndirect`，OpenGL 逐条 `glDrawElementsIndirect`，以兼容 GLES 3.1）。
`compute_test --api vulkan` 在本机 `out/cmake-vulkan`（`FILAMENT_SUPPORTS_VULKAN=ON`）
构建上 5/5 通过，包括 compute 写 SSBO → fragment 读取的跨 bind point 用例、
indirect command buffer → fragment shader 的回归用例，以及新增的
`ComputeTest.manymeshGpuLodNodeTable`：把 `buildLodGraph()`/`flattenLodGraph()` 产出的
`GpuLodNode` 表和 index buffer 原样上传为 SSBO，由 compute shader 逐节点读取
parent/level/index range 等字段并回读校验，防止 C++ 结构体与 shader 布局再次漂移。
仍然缺的是**应用层公共入口**：`Engine` 还没有暴露持久 storage buffer、compute program
和 dispatch 句柄，因此正式 Filament 渲染器无法直接提交 mmgpu 的 cut/visibility 路径。
这也是本轮把 GPU 路径放在独立 `mmgpu` 工具里验证、没有假装完成公共 API 集成的原因。

---

### 7.7.1 Filament OpenGL compute 修复与 draw-call 合并

**OpenGL compute 原先不是“能跑但慢”，而是没有真正生效。** 三个独立缺陷叠在一起：

1. `OpenGLProgram` 把 `SHADER_STORAGE_BUFFER` 和 `UNIFORM_BUFFER` 放进同一个分支，用
   `glGetUniformBlockIndex` 查询 storage block。SSBO 使用独立的 block 命名空间，这个查询
   必然返回 `GL_INVALID_INDEX`，descriptor 根本没有进入 binding map。
2. descriptor set 只在 `draw2()` 前通过 `updateDescriptors()` 延迟绑定，
   `dispatchCompute()` 没有对应调用，即使布局正确也不会提交。
3. compute shader 写入 SSBO 后没有插入内存屏障，后续 `glCopyBufferSubData`/读回或
   vertex/index/indirect 消费不保证看到结果。

修复后：SSBO 走 `glGetProgramResourceIndex(..., GL_SHADER_STORAGE_BLOCK, ...)` 和
`glShaderStorageBlockBinding()`；GLSL 的 block 名与后端/SPIR-V 的 instance 名不一致时，
用 shader 声明的 binding 做唯一匹配回退；dispatch 前调用 `updateDescriptors()`，dispatch
后插入覆盖 `GL_SHADER_STORAGE_BARRIER_BIT`、buffer update、vertex attribute、element
array 和 command/indirect 的 `glMemoryBarrier`。`compute_test --api opengl` 从
**1 passed / 1 failed** 变为 **4 passed / 1 skipped**，Vulkan 为 **5/5 passed**（均在
`out/cmake-vulkan` 构建上复测；未启用 Vulkan 的构建目录不能运行 `--api vulkan`）。

OpenGL 的 `drawIndexedIndirect` 使用 `glDrawElementsIndirect`（`glMultiDrawElementsIndirect`
不是 GLES 3.1 核心入口，逐条提交可同时覆盖桌面与移动端）。本机 Intel/WGL
驱动会拒绝“由异步/共享上下文路径分配的 buffer 直接作为 indirect source”的绘制并返回
`GL_INVALID_OPERATION`；因此实现先把命令用 GPU 侧 `glCopyBufferSubData` 拷进驱动私有
scratch buffer 再绘制，保持 GPU 驱动语义且不做 CPU 回读。Vulkan 路径直接消费原始
indirect buffer，不受此限制。

Vulkan 的第三个用例（`ComputeTest.graphicsConsumesComputeOutput`）还暴露并修复了一个
descriptor set 生命周期问题：compute 的 `commit()` 会把 `bindDescriptorSet()` 暂存的
set 消费掉，随后 graphics 的 `commit()` 找不到 set，fragment 读到全零。修复方式是在
`VulkanDescriptorSetCache` 中保留逻辑上当前绑定的 set；当 commit 的 bind point 或
pipeline layout 变化时，允许从当前 set 重新绑定。这样同一个 SSBO 可以同时用于
`VK_PIPELINE_BIND_POINT_COMPUTE` 和 `VK_PIPELINE_BIND_POINT_GRAPHICS`，不再依赖调用方
在 dispatch 和 draw 之间重复 `bindDescriptorSet()`。配合 `dispatchCompute()` 末尾的全局
`VkMemoryBarrier`（compute write → indirect/vertex/uniform/fragment/transfer read），
compute 的输出现在被 draw 正确消费。

**RenderDoc 抓帧结果**：monkey 满细节 cut（4,626 三角形）在 960×540 下提交了
**1,433 次 `glDrawElementsInstanced`**，平均每 draw 只有 3.2 个三角形；索引区间本身是
连续的，但 `mm_bench` 仍按 DAG 节点逐个建 primitive，而且 Renderable 固定保留 1,433 个
槽位，其中 1,432 个是 zero-index。逐帧遍历这些空 primitive 才是 CPU 主因，而不是
三角形数或 GPU。

`mm_bench` 现在做两层优化：

- 把同一材质、索引区间恰好相邻的 cut 节点合并成一个 draw；Renderable 的 primitive
  数量跟随合并组数，cut 改变时按需重建。
- 可选 `--compact-cut-indices`：只在 cut 变化时把当前 cut 的索引按材质拼接成一个新
  index buffer（不重建顶点），使任意 cut 都退化成每材质一个 draw。运行时若要避免每次
  cut 变化都上传，应改用 indirect/multi-draw；这里保留两种路径做对照。

| 路径（monkey，4,626 / 3,740 tris） | cut 节点 | draw calls | CPU 稳态帧时 |
|---|---:|---:|---:|
| 逐节点（`--no-merge-draws`） | 1,433 | 1,433 | 72.0 ms |
| 连续区间合并（默认） | 1,433 | **1** | **7.4 ms** |
| 逐节点 50% cut | 560 | 560 | — |
| 区间合并 50% cut | 560 | 183 | 35.7 ms |
| 50% cut + `--compact-cut-indices` | 560 | **1** | **7.05 ms** |

三种满细节路径和两种 50% cut 路径的截图均逐像素一致（RGB max diff = 0）。`--no-merge-draws`
保留用于复现瓶颈。GPU 帧时在这台机器上只有 0.21–0.22 ms，说明当前改的是 Filament/GL
提交侧开销，不是着色或三角形吞吐。

---

### 7.8 跨 UV/normal seam 的成对塌缩

OBJ 等格式在 UV 或法线不连续处会复制顶点：两份顶点的位置完全相同，但索引不同。按
per-index 拓扑看，这条接缝两侧各是一条边界；如果只塌缩其中一侧，焊接后的表面就会裂开。
质量门此前把两侧都当成不可动边界，因此 torus 只能到 66.32%。

**配对关系**

- 每个简化单元按位置建立 `PositionKey` 映射；只有恰好两份副本、且两份都被标记为边界
  顶点时，才建立双向 `seamPartner` 关系。
- 同一位置出现三份或更多副本时，AttributeSimplifier 的双向 `seamPartner` 快速路径不建立
  配对；CornerSimplifier 的焊接单元则把它们视为同一个位置，简化后再按 chart 输出
  generated 顶点。`CornerSimplifierHandlesFourChartCopiesAtOnePosition` 覆盖了 4 副本情况。

**成对评估与提交**

1. 候选边 `(remove, keep)` 必须是当前边界边；通过 `seamPartner` 找到
   `(partnerRemove, partnerKeep)`。
2. 两条边必须**同时仍是边界边**。相邻塌缩可能让旧的 partner 关系失效，此时拒绝，避免
   解锁单侧移动。
3. 两半分别按普通 `evaluateCollapse` 评估，但允许 seam 边界塌缩；任一半不合法则整对拒绝。
4. 两半替换的三角形集合必须不相交（畸形输入防护）。
5. 整对的误差取两半的最大值，避免一侧误差被另一侧掩盖。
6. 提交时先应用第一半、再应用第二半。两份副本位于接缝两侧，三角形 one-ring 不相交，
   因此结果等价于原子成对操作。

**焊接后表面验证**

每次候选通过局部检查后，再把源索引和候选索引都按位置焊接到规范 ID，比较两者的边界边
集合与流形性。只有焊接表面的边界完全不变才提交。这一步能抓住“边数没变但轮廓被改写”
或“一侧先移动”的情况；单侧边界塌缩仍会被拒绝。

`LodGraph` 构层默认开启 `seamCollapse`；公共 API 也暴露了
`AttributeSimplifyOptions::seamCollapse` / `SimplifyOptions::seamCollapse`，需要严格锁边
的调用方可以关掉。

**结果**（1280x720，同一相机，`--no-shadows`）

| 模型 | 原始面数 | 简化后 | 保留率 | PSNR / SSIM | 拓扑缺陷 |
|-|-|-|-|-|-|
| torus（seam 前） | 1,152 | 764 | 66.32% | — | 0 |
| torus（成对 seam） | 1,152 | 562 | 48.78% | 30.08 dB / 0.99195 | 0 |
| monkey | 15,744 | 7,872 | 50.00% | 40.99 dB / 0.99349 | 0 |
| sphere | 8,064 | 4,030 | 49.98% | 46.19 dB / 0.99850 | 0 |
| cloth | 74,976 | 38,098 | 50.81% | — | 0 |

表中拓扑缺陷统计非流形边、重复三角形、退化三角形和翻转三角形；torus 焊接后的边界数为 0。
截图位于 `out/seam-angle-original.png`、`out/seam-angle-50.png`、`out/seam-angle-75.png`、
`out/seam-monkey-original2.png`、`out/seam-monkey-50.png`、`out/seam-sphere-original.png`
和 `out/seam-sphere-50.png`。人工目视对比未发现洞、裂缝或明显破面；torus 与 monkey 在
50% 档可见地变粗，但轮廓和主要特征保持完整。

**限制**：AttributeSimplifier 的快速路径只对精确的两副本建立配对；三份以上同位置副本
需要走更慢的 corner 焊接路径。跨 chart 的 QEM 新位置已经能生成顶点并插值属性，但极端
情况下仍会触发几何/属性门而提前停止。这里没有放松质量门来换取更低的三角形数。

**3+ 副本与 UV 一致性（2026-10 回归）**

- `CornerSimplifierHandlesFourChartCopiesAtOnePosition` 覆盖 4 份副本的拓扑；新增的
  `CornerSimplifierKeepsAttributesOfThreeChartCopiesAtOnePosition` 用三个扇形 chart 组成
  闭合圆盘，中心位置有 3 份不同 UV/normal 的副本，并验证简化后没有把不同 chart 的属性
  合到同一个输出顶点。
- 新增 `LodGraphKeepsThreeChartCopiesAndTheirUvIslands` 走完整 pipeline：`buildLodGraph`
  → `selectLodGraphAtRatio` → `compactLodSelection`，确认存在一个跨三个 chart 的简化
  父节点，并逐三角形检查每个顶点仍匹配某一个 chart 的仿射 position→UV 映射。
- 这条端到端测试暴露了一个真实问题：粗层级里同一个 chart 顶点在相邻三角形上的
  barycentric 外插会分叉，实测 UV 差可达 0.04。旧代码把这些 corner 平均后输出，结果是
  位置和 UV 不再对应，纹理会在少数三角形上拉花；旧版本因此把分歧落点直接拒绝。
- 当前实现改为按 `sourceVertex` 和 UV cluster 分区：位置相同的多个 generated vertex
  可以并存，每个三角形引用自己 chart 的 UV/normal/AO。表面仍按位置焊接，所以不会开洞；
  新增 `CornerSimplifierEmitsOneVertexPerDivergentUvCluster` 专门断言同位置多顶点、
  UV 岛不被混合、拓扑仍 closed。`--corner-split-uv 0` 可关闭拆分做 A/B，默认开启。
- 同目标 A/B（`mmgeo --mode dag`，同质量门）：torus `--target-ratio 0.2` 两者都是
  **550 / 1,152 = 47.74%**，拆分版 cut 625 顶点（594 generated）对平均版 587（556
  generated），多出的 38 个顶点就是同位置 UV 变体；monkey `--target-ratio 0.3` 拆分版
  **7,124 / 15,744 = 45.25%**，平均版 **7,256 / 15,744 = 46.09%**，拆分版少 132 个
  三角形且 cut 顶点 7,867 对 7,922。两者拓扑均为 non-manifold/duplicate/degenerate/
  flipped = 0，UV 符号与面积比统计接近；拆分版用少量顶点换掉了 UV 平均的隐患。

---


### 7.9 着色补偿：能补什么、补不了什么（实测）

减面后的损失能不能用着色补回来？这一轮把整条链路做出来并量了一遍。

新增能力：

- `DetailBake`（`mmgeo --bake-normal N`）：把源网格法线场与 LOD 插值法线场之差，烘到
  LOD 的 UV 布局里，输出 `detail-normal.png`（切线空间，neutral = `(128,128,255)`）。
  只保留 LOD 丢掉的那部分，低频形状仍由 LOD 自己的顶点法线承担。
- `computeUvTangents()`：按 UV 参数化计算逐顶点切线和手性，镜像 chart 会自动得到正确的
  bitangent 符号。`mm_bench` 的 LOD 顶点缓冲改用它（之前是任意正交基）。
- `mm_bench --detail-normal <png> --normal-strength s`，材质
  `samples/materials/aiDetailNormal.mat`（带 `specularAntiAliasing: true`）。
  `--roughness` 可单独做粗糙度补偿实验。
- `repairShadingNormals()`（`mmgeo --shade-crease DEG`、`mm_bench --shade-crease DEG`，
  UI 里的 “Smooth seam normals”）：只改着色法线，不改一个三角形。把同位置、
  夹角小于 crease 的重复顶点法线按三角形内角加权平均，保留真实硬边。

实测（960×720、同机位、`--no-shadows`、monkey，参考为 15,744 面全分辨率）：

| 变体 | PSNR | SSIM |
| --- | --- | --- |
| LOD 7,084 面（44.99%） | 37.17 dB | 0.98708 |
| LOD + 细节法线（s = 1.0） | 36.70 dB | 0.98311 |
| LOD + 细节法线（s = 0.25） | 37.12 dB | 0.98638 |
| LOD + 只开 specular AA（s = 0） | 37.18 dB | 0.98707 |
| LOD + roughness 0.55 | 37.19 dB | 0.98672 |

烘焙本身是有效的：monkey 45% 覆盖 97.4% UV，丢失法线细节 **mean 1.28° / max 89.98°**
（568 个 UV 错配 texel 被保持 neutral、不计入均值）；monkey 38% 为 **mean 1.45°**。
放大对比图里，细节法线反而在眼窝、口鼻边缘多出细碎明暗带。

把误差按像素拆开看更能说明问题：monkey 44.99% 时，轮廓 ±2 px 只占 **1.5%** 的像素，却贡献
**73.4%** 的平方误差；轮廓内部 PSNR 仍有 **42.85 dB**。着色不可能修正轮廓覆盖。

原因不是烘焙错了，而是这条管线本身没有法线头寸：

1. corner 简化**携带**高分辨率法线（`GeneratedVertex.normal`），LOD 顶点法线就是源法线，
   三角形内部只剩线性插值误差（均值 0.7–1.6°），远小于几何位移。
2. 参考图与 LOD 在同一个像素上采样的是**不同表面点**。把源表面在对应 UV 处的法线贴回
   LOD，会让该像素的着色偏离参考图的该像素，所以逐像素 PSNR/SSIM 下降。
3. 真正丢掉的是轮廓、遮挡/接触阴影、薄几何和投影；这些不是着色能补的。

仍然值得用的场景：源资产有**顶点密度表达不了**的微表面细节（雕刻→游戏网格的
normal/AO 烘焙），且 LOD 是低频代理而不是“保留原法线的抽稀”。本项目的默认建议是：
不给携带法线的 LOD 贴细节法线；近处用更细的 LOD（`--distance-lod`），远处再降。
着色层下一步的优先级是 AO/cavity 烘焙，而不是细节法线。

UV 布局还有一条硬限制：单张 2D 法线贴图只能表示 `[0,1]` 的 atlas。baker 现在会检查
LOD 实际引用的 UV：torus 的生成顶点把 UV 推到 `[-0.020, 1.047]`，cloth 是
`[-2.39, 5.01] x [0, 3.70]` 的平铺布局，两者都会被**拒绝**并给出提示；要用得先做唯一化
atlas（或每个 tile 烘一张），否则不同表面点会写进同一个 texel。monkey 的 UV 在 `[0,1]`
内，是当前唯一通过检查的测试资产。

**高度/视差补偿（新增，实测收益接近零）**：细节法线只能改着色，不能改“在 UV 的哪里
采样”。`DetailBake` 因此新增 `bakeDetailHeightMap()`：把源表面与 LOD 表面都光栅化到
同一张 `[0,1]` UV atlas，对每个共同覆盖的 texel 计算

```text
height = dot(sourcePosition - lodPosition, lodNormal)
```

再以 128 为中性编码到 R8，输出 `detail-height.png` 和记录
`recommendedUvScale` 的 `.txt` sidecar。这个定义比“沿 LOD 法线双向打射线”更稳：
后者在共面表面上会漏采样，也会把模型另一层表面误当成细节。修正后 monkey 45% 档的
miss 从 **12,070** 降到 **5,481**，平均绝对位移从 **0.0106** 降到 **0.00154**；
38.19% 档为 **6,408 misses / mean |h| 0.00169**。两个档位的推荐视差尺度都约为
**0.0414**，512×512 烘焙约 **163–172 ms**。

材质 `samples/materials/aiParallax.mat` 用迭代视差采样这张图，`mm_bench` 暴露
`--detail-height`、`--parallax-scale`、`--parallax-layers`、`--parallax-strength` 和
对应 UI 滑杆。方向已核对：Filament 的 `getWorldViewVector()` 是片元指向相机，因此
“源表面在 LOD 前方”时正高度应对应
`uv = baseUv + height * viewTangent.xy / viewTangent.z`，当前符号是正确的。

960×720、`--no-shadows`、同一机位、细节法线 + POM 的结果：

| monkey 44.99% 变体 | PSNR | SSIM |
| --- | --- | --- |
| 细节法线，POM 0 | 40.39 dB | 0.99300 |
| 细节法线，POM 1.0 | 40.43 dB | 0.99306 |
| 细节法线，POM 2.0 | 40.45 dB | 0.99308 |

更激进的 38.19% 档也只有 **40.05 → 40.10 dB**。4 视角重复后差异消失：POM 0 的
median / minimum 为 **42.40 / 40.05 dB**，POM 2.0 为 **42.38 / 40.10 dB**；SSIM
median 从 0.99534 降到 0.99529。也就是说，单视角上的 0.06 dB 不是稳健收益。原因同样
是没有法线头寸：monkey 的 LOD 已经保留了源法线，真正
丢掉的是轮廓、薄几何和遮挡；POM 只能让内部 texel 换一个采样位置，不能增加轮廓覆盖。
从高度场再求梯度生成“微法线”的实验也失败了：1× 强度会在特征边缘产生明显的黑色结壳
（32.65 dB），0.1× 仍有暗边（40.04 dB），所以没有进入默认材质。

结论：POM 是**可选的高度细节工具**，适合源资产本身有真实位移/微表面、而 LOD 是低频
代理的情况；对本项目当前“携带源法线抽稀”的资产，默认关闭。生产上优先级仍是
**近细远粗的几何 + 源网格 AO + 接缝法线修复**，而不是继续加大 POM 强度。

**接缝法线统一（shading-only，实测）**：简化后的 `selected.ply` 有 7,724 个顶点，但只有
3,628 个唯一位置；2,179 个位置组里同位置法线的中位差为 **2.47°**、P90 为 **11.11°**、
最大 42.09°。这些缝在低模上会变成可见的明暗硬边。`--shade-crease 10` 之后，重复组法线
中位差降到 **0.01°**，大于 5° 的重复法线对从 **2,318/7,610** 降到 **1,330/7,610**，
而最大 42.09° 的真实折边保持不合并。

| monkey 44.99% 变体 | PSNR | SSIM |
| --- | --- | --- |
| 原始 LOD 法线 | 41.90 dB | 0.99500 |
| `--shade-crease 5` | 41.89 dB | 0.99499 |
| `--shade-crease 10` | 41.90 dB | **0.99509** |
| `--shade-crease 20` | 41.87 dB | 0.99505 |
| `--shade-crease 30` | 41.78 dB | 0.99515 |

torus 46.70% 上更干净：**45.81 → 45.91 dB**、**0.99825 → 0.99844 SSIM**（crease 10）。
目视上 10° 能消掉鼻梁/右颊的细碎法线带；20°/30° 会把眼窝这类真实折边也抹平，出现
暗斑，所以 UI 默认开启档是 **10°**，硬表面资产建议 5° 或关闭。它仍然只是“补着色接缝”，
轮廓、遮挡和几何位移不在可补范围内：monkey 45% 时轮廓 ±2 px 占 1.5% 像素、贡献 73.4%
平方误差。要进一步提升观感，优先级仍是近细远粗的 LOD 和轮廓保护，而不是更大的 crease。

补偿强度现在是连续的：`--shade-strength F`（0..1）和 UI 的 `Shading strength` 滑杆把每个
重复位置法线向 cluster 平均值线性插值，而不是只能全开或全关。`F=0` 完全保留原法线，
`F=1` 等价于原来的满强度修复。UI 同时暴露 `Normal detail`（细节法线强度）和 `Roughness`
滑杆，便于在编辑器里做“几何更省 / 着色补回”的 A/B。

**自动强度（实测）**：`--shade-auto` 和 UI 的 “Auto strength (screen error)” 不再要求
美术猜一个固定值。最坏屏幕误差 < 0.25 px 时接缝变化不可见，强度为 0；0.25→1 px 平滑
升到 0.50；≥1 px 保持在 0.50。上限不是 1.0，因为全强度会把真实法线变化一起抹平。
960×720、固定机位、`--no-shadows`、monkey 44.99% 的 A/B：

| `--shade-strength` | PSNR | SSIM |
| --- | --- | --- |
| 0（原法线） | 41.84 dB | 0.99494 |
| 0.25 | 41.91 dB | 0.99523 |
| 0.50 | **41.93 dB** | **0.99535** |
| 0.75 | 41.90 dB | 0.99529 |
| 1.00 | 41.83 dB | 0.99504 |

在 62.1% 和 38.2% 两个更轻/更重的 cut 上，0.50 同样优于 0 与 1.0（分别约 +0.09 dB
和 +0.08 dB），所以自动策略在可见误差区间停在 0.50，而不是随减面比例继续加码。这个
自动值只影响接缝法线；轮廓、遮挡、薄几何和几何位移仍然补不回来。

**屏幕空间 cavity（新增，实测偏负）**：`samples/materials/aiCavity.mat` 在 fragment 里用
`dFdx/dFdy` 估计世界空间平均曲率，只压暗凹处；`--shade-cavity F` 控制强度，UI 里有
“Cavity shading” 滑杆，`--curvature-scale` 控制世界尺度（默认由包围盒自动求）。它必须
配合 IBL 或阴影，因为纯直射光下 `MaterialInputs.ambientOcclusion` 不参与最终颜色；默认
`aiDefaultMat` 不包含这段代码，开启时需要显式选择 `aiCavity.filamat`。

960×720、`lightroom_14b` IBL、monkey 44.99%、参考为 15,744 面高模：

| 变体 | PSNR | SSIM |
| --- | --- | --- |
| LOD | **36.29 dB** | **0.99293** |
| LOD + cavity 0.10 | 36.00 dB | 0.99203 |
| LOD + cavity 0.25 | 34.85 dB | 0.98869 |
| LOD + cavity 0.50 | 31.54 dB | 0.98047 |

结论：**这不是一个默认开启的“补画质”开关**。本管线的 LOD 已经携带源法线，屏幕空间曲率
看到的是低模自身的面片梯度，压暗的是低模折面，而不是高模丢掉的细节；0.25 已能在眼窝/
鼻翼看出效果，但会把低模的面片感一起放大。保留它作为美术可调的实验材质，默认强度 0。
真正能补回这一层的顺序是：源网格 AO/cavity 烘焙（不是屏幕空间近似）→ 高度/位移或 POM
→ 时域/神经重建；轮廓、薄几何和几何位移仍然补不回。

**源网格 AO 烘焙（新增，实测有效）**：`AmbientOcclusion` 用 BVH 对源网格做余弦半球
可见性采样，把结果烘到 LOD 顶点上。它不需要 UV atlas，因此 tiled/越界 UV 的 torus 和
cloth 也能用。每条射线从顶点沿源网格法线偏移后发射，长度默认取源包围盒对角线的 10%；
QEM 生成点可能落在源表面内侧，所以采样前先吸附到最近源三角形，否则整个实体会被判成
全遮挡。重复位置顶点在采样后焊接平均值，避免 LOD seam 上出现一条细 AO 缝。

`mm_bench --bake-ao --ao-samples 32 --ao-strength 0.5`（材质 `aiBakedAo`，UI 里有
“Baked AO” 滑杆）和 `mmgeo --bake-ao 32 [--ao-radius R]`（写进 PLY 顶点色 R）使用同一套
烘焙。960×720、`--no-shadows`、monkey（15,744 → 8,660 面，55.01%，32 samples，自动半径
0.365，21,774 个 LOD 顶点，烘焙约 150–190 ms）：

| `--ao-strength` | PSNR | SSIM |
| --- | --- | --- |
| 0（LOD 原样） | 41.64 dB | 0.99560 |
| 0.25 | 44.00 dB | 0.99640 |
| **0.50** | **44.92 dB** | **0.99660** |
| 0.75 | 43.37 dB | 0.99603 |
| 1.00 | 40.91 dB | 0.99482 |

三视角重复验证（median / minimum）：无 AO 为 **45.35 / 41.64 dB**，AO 0.50 为
**48.21 / 44.92 dB**；SSIM 0.99804 → 0.99845。AO 只补遮挡，不改变三角形或轮廓。
在 62.0%、55.0% 和 45.0% 三个 cut 上，0.50 分别带来 **+3.78 / +3.28 / +2.69 dB**，
所以默认强度固定为 0.50，而不是随减面比例继续加码。与 `--shade-crease 10` 叠加再得
约 **+0.10 dB / +0.00023 SSIM**，两者可以同时开。

> **参考系更正（重要）**：上面的 41.64 → 44.92 dB 是把 LOD+AO 与**同样开了顶点 AO 的
> 高模参考**比较，也就是“材质一致”的对比。它对“未开 AO 的高模参考”并不成立：同一组
> 960×720 monkey 44.99% 图，参考改成未开 AO 时，LOD 从 **42.51 dB** 掉到 **40.45 dB**
> （顶点 AO）或 **41.77 dB**（贴图 AO）。因此 AO 的定位是**恢复高模本来就有的接触阴影**，
> 不是凭空把未阴影的高模外观补回来。生产接入时必须让高模与 LOD 使用同一种 AO 表达，
> 否则逐像素误差反而变大。

> **视觉复验（本轮）**：固定机位、960×720、`--no-shadows`、单帧、monkey 55.01% cut，
> 参考为 `--dag --savings 0 --bake-ao` 的高模 + 顶点 AO：LOD 不开 AO 为
> **41.49 dB / 0.99595**；LOD + AO（0.50）为 **46.20 dB / 0.99718**，平均绝对差从
> 0.001146 降到 0.000380；再叠 `--shade-crease 10` 为 **46.21 dB / 0.99721**。
> 即 **+4.71 dB**、误差降到约 1/3，与上面的三档结果同向（相机不同，绝对值不同）。
> 目视上恢复的是眼窝、眉弓、鼻翼和耳廓的接触阴影；轮廓台阶与薄几何没有变化。

**统一着色补偿材质（新增，opt-in）**：`samples/materials/aiLodCompensated.mat` 把两条
AO 路径合成一个材质：高模源 UV 烘出的 AO 贴图（`aoMap`，覆盖比顶点更细的腔体）与 DAG
顶点 AO（顶点色 R，UV atlas 不可用时仍有效）取 `min`，再按 `aoStrength` 混合；可选的
`normal` 是 `DetailBake` 输出的高模→当前 cut 切线空间细节法线，`roughnessBoost` 用来把
失去的法线方差折算进高光粗糙度。`detail-normal.png` 的 alpha 存归一化丢失角
（`angle / 90°`），材质的 `roughnessBoost` 只在 alpha 高的纹素上生效；旧的三通道贴图按
alpha=1 读取，保持原行为。可选的 `heightMap` 走与 `aiParallax` 相同的迭代视差，
并用同一个 UV 采样 normal/AO。`compensationStrength` 是运行时总闸门：0 时材质完全不
改变 LOD，1 时按上述参数生效；因此 UI 可以让该材质常驻并即时 A/B。
`mm_bench --shade-compensate` 选择该材质，
`--compensate-size 512` 控制运行时烘焙分辨率，`--compensate-normal` 控制细节法线
（默认负值：运行时烘焙自动 0，显式 `--detail-normal` 自动 1），`--roughness-boost`
默认 0；`--parallax-strength` 默认负值，只有显式 `--detail-height` 时才自动为 1，
避免没有高度图时白跑视差循环。UI 勾选 “Shading compensation (AO + detail)” 或按 `C` 即时开关，
`--compensation-strength 0..1` 与 UI 的 Compensation amount 滑杆调总强度；Normal detail /
Roughness compensation 滑杆和 “Rebake maps for this cut” 按钮用于美术微调。切换 cut 后
细节法线需要按新三角形重烘，AO 贴图只烘一次。无 UV、平铺 UV 或越界 UV 时，贴图烘焙失败
会自动改为顶点 AO（并重传紧凑顶点缓冲），不再停留在白色 AO 贴图。

着色补偿的作用域可以按误差来源拆开看：

| 误差来源 | 着色能否补 | 当前手段 |
| --- | --- | --- |
| 接缝/重复顶点法线不连续 | 能，且最稳定 | `repairShadingNormals()` / `--shade-crease 10` |
| 腔体、接触阴影、方向性可见度 | 部分 | 顶点 AO、AO 贴图、bent normal |
| 当前 cut 的褶皱/接触遮挡 | 部分，只乘间接光 | GTAO / SSCT（`--ssao` / `--ssct`） |
| 被删掉的微法线 | 部分，依赖 UV/切线框架 | 高模→LOD 细节法线 |
| 高光比剩余几何更锐 | 统计近似 | 丢失角→逐纹素粗糙度 |
| 轮廓、薄几何、真实位移、覆盖错位 | **不能** | 几何质量门、MSAA、近细远粗、高模阴影代理 |

因此正确的组合不是“把材质强度拉满”，而是先用几何/近细远粗守住轮廓，再用着色补表面。
29.38% monkey 档的实测里，轮廓 XOR 只占 0.19% 像素却贡献 66.7% 平方误差；这部分无论
AO、法线、POM 还是粗糙度都不会改善。

逐纹素粗糙度的 45.25% monkey 复验：256² 细节图里丢失角平均 1.02°、最大 88.19°，
alpha 平均 1.59/255，34.0% 纹素非零，alpha>32 的只有 257 个。960×720、固定材质、
`--no-shadows` 下，`roughnessBoost=0` vs `0.5` 为 **41.088 vs 41.094 dB**，只有
0.008% 像素变化超过 1 LSB（最大 10 LSB）。把同一张图的 alpha 人为设成 255 后，
`0.5` 与 0 的差异扩大到 48.9 dB / 1.86% 像素，确认 shader 读取的是逐纹素 alpha。
因此这条不是靠“整体加粗糙度”换稳定，而是只在烘焙确实发现丢失细节的地方生效。

同一机位、960×720、`--no-shadows`、monkey 44.99% cut 的实测（每个候选都与**使用同一
材质表达的高模参考**比较，避免 AO 参考系混淆）：

| 方案 | PSNR | SSIM | 说明 |
| --- | --- | --- | --- |
| LOD 无补偿 vs 高模无补偿 | **42.60 dB** | 0.99559 | 保留源法线 + 自动接缝法线 |
| LOD 顶点 AO 0.50 vs 高模顶点 AO | **43.36 dB** | 0.99558 | 当前推荐默认 |
| LOD 512² 贴图 AO vs 高模贴图 AO | 42.77 dB | 0.99529 | 与无补偿接近；顶点密度足够时不划算 |
| LOD 细节法线 vs 高模细节法线 | 41.64 dB | 0.99412 | 当前 UV/切线框架下反而降低 PSNR |

结论：着色策略能补的是**低频可见性（AO）和微法线响应**；在本项目当前“保留源法线抽稀”的
LOD 上，顶点 AO + `--shade-crease` 是唯一稳定收益项，512² 贴图 AO 没有明显超过顶点 AO，
细节法线和 roughness boost 只能作为美术开关。轮廓覆盖、薄几何、接触几何和位移仍由几何
本身决定；如果资产必须有这些，应回到减面质量门或离线高模→低模烘焙，而不是继续加屏幕
空间强度。monkey 45% 时轮廓 ±2 px 只占 1.5% 像素却贡献 73.4% 平方误差，这是着色无法
跨越的上限。

**45.25% 档的误差上限（固定机位复验）**：960×720、`--no-shadows`、显式机位
`eye 1.982729,1.347563,4.480644 / target 0,-0.015564,0.019503`，monkey 7,124 面对
11,250 面的 DAG 满细节参考。按前景掩码拆分后，轮廓 XOR 仅 **736 px（0.11%）**，却贡献
**68.3%** 的平方误差；两图共同覆盖区的 PSNR 为 **37.24 dB**，整图为 42.50 dB。着色只能在
共同覆盖区内争取收益，逐个候选都与使用同一材质表达的高模参考比较：

| 方案 | 共同覆盖区 PSNR | 相对无补偿 |
| --- | --- | --- |
| LOD 无补偿 | 37.24 dB | — |
| 缝法线 10° / auto | **37.42 dB** | **+0.18 dB** |
| AO 0.50 | 37.28 dB | +0.04 dB |
| AO + 细节法线 0.25 | 37.17 dB | -0.07 dB |
| roughness 0.40 / 0.60 | 36.25 / 36.62 dB | -0.99 / -0.62 dB |

固定机位下，稳定的着色收益只有接缝法线；AO 的收益依赖视角和腔体可见度，细节法线与
粗糙度调整都不能替代几何。复验图与 JSON 在 `out/shade-detail-check/`，整图 PSNR 依次为
42.50 / 42.57 / 42.71 / 42.67 / 42.35 / 42.49 dB。这个拆分也说明为什么继续加 AO 或法线
强度无法跨越 30–45% 档：大部分平方误差来自轮廓覆盖，而不是表面 BRDF。

**着色项与边缘项的分工（本轮新增复验）**：上表说明材质项的作用范围。为了确认
“把着色强度拉满”是否能跨过上限，本轮又补了两组同机位、同参考系的对照：

| 方案 | 整图 PSNR | 共同覆盖区 PSNR | 轮廓 XOR 平方误差占比 |
| --- | --- | --- | --- |
| LOD 无补偿 | 42.50 dB | 37.24 dB | 68.3% |
| 缝法线 10° / auto | 42.57 dB | 37.42 dB | 69.1% |
| LOD 与参考都开 TAA | 41.00 dB | 31.40 dB | 6.9% |
| tiny CNN 跨资产推理 | 42.65 dB | 36.85 dB | 64.1% |
| 缝法线 + tiny CNN | 42.70 dB | 36.96 dB | 64.6% |

TAA 两边都开、60 帧收敛后仍只有 41.00 dB / SSIM 0.99160（无 AA 为 42.50 / 0.99555）。
它的 jitter 确实把轮廓 XOR 压到 6.9%，但代价是共同覆盖区从 37.24 掉到 31.40 dB，
也就是把内部细节整体拖糊；静帧画质应选 MSAA，TAA 只在有真实运动矢量/时域采样
预算时使用。tiny CNN 的整图 +0.15 dB 则来自边缘（XOR 占比降到 64.1%），内部反而
-0.39 dB，但整图 SSIM 从 0.99555 升到 0.99583；它证明学习型重建能补“边缘/高频”，
但不是 AO 或细节法线的替代品。dragon 同资产训练的 tiny 为 +1.88 dB，跨资产只剩
0.15 dB，说明网络学到的是资产先验，部署需要多样本训练或按资产 fine-tune，
不能指望一个通用模型无条件补回所有模型。复验图与 JSON 在 `out/temporal-check/`。

因此推荐按保留率选补偿：≥45% 用缝法线 + 顶点 AO 0.5（参考必须同 AO 表达）；
25–45% 用 4× MSAA + 缝法线，AO 只按 cluster 误差淡入；<25% 优先几何落点、近细远粗、
高模阴影代理或学习型重建，不再继续加 AO/法线/roughness。UI 的 measured preset 和
`--shade-error-driven` 已按这个判据实现。

**三模型 / 三视角复验（本轮）**：960×720、`--no-shadows --auto-frame --ignore-ceiling`、
每个候选裁到约 45–47% 面数。比较时高模和 LOD 使用**同一种 AO 表达**；monkey 用 256²
AO 贴图，torus 用 256² AO 贴图，cloth 的 UV 是平铺/越界布局，自动走顶点 AO 回退。

| 模型（保留面数） | LOD 无补偿 | LOD + 着色补偿 | delta | SSIM |
| --- | --- | --- | --- | --- |
| monkey 44.99% | 45.83 dB | **46.36 dB** | **+0.53 dB** | 0.99700 → 0.99812 |
| torus 43.23% | 45.70 dB | 45.69 dB | -0.01 dB（中性） | 0.99813 → 0.99814 |
| cloth 46.98% | 38.54 dB | **44.12 dB** | **+5.58 dB** | 0.99238 → 0.99539 |

monkey 的收益集中在眼窝、眉弓、鼻翼、耳廓；torus 没有腔体，AO 均值 0.998，所以几乎
不改变画面；cloth 是开放薄面，顶点 AO 均值只有 0.492，单独对照**未开 AO 的高模**会显得
更暗（38.21 vs 44.52 dB），但对**同样开顶点 AO 的高模参考**提升 5.58 dB。这再次说明：
着色补偿恢复的是高模已经存在的可见性响应，不是凭空恢复未阴影的外观。

同一 monkey 三视角上，AO-only 为 46.36 dB；再叠加细节法线降到 **45.36 dB**（-1.00 dB），
roughness +0.10 降到 **42.42 dB**（-3.94 dB）。因此默认仍只开 AO，细节法线和 roughness
保留为美术开关。`compensationStrength=0` 与普通材质渲染的差异为 69.91 dB PSNR、
平均 0.000013/255，仅 0.2% 像素超过 1/255，来自组合材质的 `specularAntiAliasing`，
视觉上不可见。

半径在 monkey 上并不敏感：0.15 / 0.365（自动）/ 0.75 / 1.5 的 PSNR 都是
**44.91–44.92 dB**，SSIM 在 0.99658–0.99669 之间；自动值足以覆盖眼窝和耳廓。torus 是
无腔体的封闭光滑面，AO 均值 0.994，效果近似中性（45.81 → 45.80 dB），目视没有压暗；
这同时验证了吸附修复：修复前有生成点落在实体内部，torus 的 AO 最小值被错误地压到
0.000，内圈出现明显黑带。

生产接入时要注意三点：AO 应优先乘到 IBL/环境光项，`aiBakedAo` 为了在只有直射光的
headless 对比里可见，同时乘了 `baseColor` 和 `ambientOcclusion`；源资产已有 AO 贴图时
要避免二次压暗；蒙皮/形变网格需要按变形后的位置重烘或用预烘的局部 AO。`mm_bench`
上传时已把 AO 压成 `UBYTE4`（相对 `FLOAT4` 每顶点 16 → 4 字节，实测末位量化误差
PSNR 78.34 dB）。**AO 字段现已进入生产格式（本轮）**：`Mesh::ao` 是可选的源顶点字段，
corner 简化按重心坐标把它插值到生成顶点（并 clamp 到 `[0,1]`，避免外插把可见度算到
大于 1），`mmgeo --ao-field N` 在源网格上烘一次（monkey 9,908 顶点 / 16 samples /
自动半径 0.365，约 46–74 ms），随后每个 DAG 节点、每个 cut 都自带 AO，不再按 cut 重烘。
`lod_graph.mmb` 升到 **format version 7**：生成顶点记录从 9 个 word 增到 10 个（每顶点
+4 B），旧版本文件仍可读，缺失的 AO 默认为 1.0（无遮挡）。实测 monkey 生成顶点的 AO
范围 0.000–1.000、均值 0.861，与源网格均值 0.837 一致；导出的 PLY 红通道 209 个不同取值。
`test_manymesh` 新增 `LodGraphCarriesAmbientOcclusionThroughSimplification`，覆盖插值、
序列化往返和 `appendGeneratedVertices` 的 AO 扩展。
着色不能补回轮廓覆盖、薄几何、接触几何和几何位移——monkey 45% 时轮廓 ±2 px 只占
1.5% 像素却贡献 73.4% 平方误差。

**高模阴影代理（新增，opt-in，实测中性）**：`--shadow-proxy` 让源网格（或
`--shadow-proxy-ratio <1` 选的更细 DAG cut）只参加阴影贴图，不写主相机颜色和深度。
`samples/materials/shadowProxy.mat` 声明 `colorWrite : false`、`depthWrite : false`；
Filament 的 depth variant 仍会把代理写入阴影图，所以主相机看不到它，阴影接收面却能用
它的几何。代理与可见 LOD 共享 `g_lodVertexBuffer`，只多一条 index buffer；启用后
LOD 自身停止投影，避免两套轮廓同时进阴影图。UI 有 “High-poly shadow proxy” 复选框
（快捷键 `P`）、`Shadow proxy detail` 比例滑杆，以及 `Shadow bias` /
`Shadow normal bias` 两个 offset 滑杆。

这里有一个必须调 bias 的原因：源网格与 LOD 表面不是同一个面，太阳默认的
`constantBias=0.001` / `normalBias=1` 会把 LOD 接收面判成被高模自身遮挡，额头出现细黑
条纹。代理启用时默认改为 **0.010 m / 3.0**，条纹消失；代价是偏移过大时接触阴影会
轻微脱离。960×720、monkey、同一显式机位、默认材质、太阳阴影的实测：

| 档位 | 无代理 | + 高模阴影代理 | 代理 vs 无代理改变像素 |
| --- | --- | --- | --- |
| 55.01% | 31.23 dB / 0.99079 | 31.19 dB / 0.98895 | 0.35% |
| 45.25% | 31.09 dB / 0.98949 | 31.08 dB / 0.98780 | 0.36% |

结论要如实写：**单物体自阴影上它不是 PSNR 收益项**。高模与 LOD 的阴影贴图差异本来
只覆盖约 0.3% 像素，1024² 阴影图又抹平了更细的腔体；代理的收益应该出现在“高模角色
把耳廓/手指/武器轮廓投到地面或其他物体”这类跨物体接触阴影上，以及阴影图分辨率更高的
场景。它仍然补不了屏幕空间轮廓覆盖，且多一次高模深度绘制，所以默认关闭；保留为生产
渲染器可选的 shadow-only proxy 路径，不要当作减面后的通用画质修复。

**按 cluster 屏幕误差加权（新增，opt-in）**：一个 cut 会同时包含近处细节点和远处粗节点，
统一补偿强度必然对其中一类过度或不足。`recommendedShadingCompensationWeight()` 在
0.25 px 以下返回 0、1 px 达到 1；`mm_bench --shade-error-driven` 把它写进顶点色 alpha，
`aiLodCompensated.mat` 用 `compensationStrength * alpha` 统一门控 AO、bent normal、
细节法线和 POM。这样近处 cluster 保持原始清晰度，粗 cluster 才吃补偿；顶点色 alpha 是
新增的材质契约。单物体 monkey 50% cut（640×360、128² AO、16 rays）全局 vs 误差加权为
**43.76 → 43.73 dB**，差异基本是噪声级，所以它不是 PSNR 收益项，默认关闭，价值在
混合近远 cluster 的场景里避免“远近一刀切”。组合材质同时启用
`specularAmbientOcclusion : simple`，AO 会衰减高光 IBL；顶点色 G/B 可选携带 bent normal。

**运行时屏幕空间 AO / 接触阴影（新增，opt-in）**：烘焙 AO 知道源网格的腔体，但它不知道
运行时实际画出的 cut 在哪里；GTAO 正好相反。`mm_bench --ssao` 在 View 上启用 Filament
GTAO，`--ssct` 在同一个 SSAO pass 里沿主光方向做 screen-space cone trace，把当前深度
缓冲中仍能看到的褶皱和接触暗部加回间接光。两者都不需要 UV、源网格或离线烘焙，适合
无 UV 资产和动态 DAG cut；代价是每帧一次深度预处理和全屏 AO。UI 的
“Screen-space AO (GTAO)” / “SSCT contact shadows” 可以实时 A/B，半径 0 自动取包围盒
对角线的 10%，SSCT 的距离 0 自动取 25%；`SSAO quality` 和 `SSAO resolution`
（Half/Full）分别控制采样预算和 AO buffer 分辨率，与 CLI 的
`--ssao-quality` / `--ssao-resolution` 共用同一状态。

比较这类屏幕空间项时必须让高模参考和 LOD 用同一种设置，否则指标会变成“谁多了一层
暗部”而不是“谁更接近”。960×720、`--no-shadows`、`--ibl`、3–4 视角、固定机位的实测
（PSNR 中位数 / SSIM 中位数）：

| 资产与档位 | 无 SSAO | GTAO | GTAO + SSCT |
| --- | --- | --- | --- |
| cloth 48.09% | **44.82** / 0.99808 | 44.85 / 0.99808 | **45.04** / 0.99809 |
| monkey 45.25% | **41.68** / 0.99692 | **41.72** / 0.99692 | 未单测 |
| torus 47.74% | **39.19** / 0.99675 | 未单测 | 39.20 / 0.99673 |

结论是：SSAO/SSCT 是**当前 cut 的可见性补偿**，不是几何替代品。它在布料这种大片连续
褶皱上最有效（+0.22 dB），对 monkey 只有 +0.08 dB，对 torus 基本中性；它不会把轮廓、
薄几何或已经被合并掉的腔体变回来。全分辨率 High 在 960×720 上的 GPU 中位增量约
**+2.1～2.5 ms**；半分辨率 Medium + SSCT 在 cloth 上仍是 **45.04 dB / 0.99809**，
GPU 增量约 **+0.88 ms**。因此移动端优先半分辨率 Medium，桌面静态对比再用全分辨率
High。若资产已经有可靠的源 AO 贴图/顶点 AO，烘焙 AO 仍是主路径；SSAO 用来补
“cut 自己产生的接触关系”，两者可以同时开，但比较时必须保持参考表达一致。

**29.38% 极限档复验（本轮）**：同一 1024×640 机位、`--no-shadows`、monkey
15,744 → 4,626 三角形（29.38%，boundary 168 与源一致，其余拓扑缺陷 0），参考为高模 +
同一张源 UV AO 贴图。结果说明着色补偿在极限档的边界在哪里：

| 变体 | PSNR | SSIM | 相对基线 |
| --- | --- | --- | --- |
| LOD 无补偿 | **39.78 dB** | 0.99159 | — |
| + AO 贴图（strength 0.5） | 39.81 dB | 0.99083 | +0.03 dB |
| + 细节法线 0.25 | 39.79 dB | 0.99077 | +0.01 dB |
| + 细节法线 1.0 | 39.46 dB | 0.98934 | -0.35 dB |
| + 细节法线 1.0 + POM 1.0（正视） | 39.46 dB | 0.98934 | 与无 POM 相同 |

误差拆分：轮廓 XOR 只占 **0.19%** 像素，却贡献 **66.7%** 的平方误差；±2 px 轮廓带占
1.03% 像素 / 72.7% 误差；轮廓内部 PSNR 为 35.16 dB。也就是说该档即使把内部着色做到
完美，整图上限也只有约 45.4 dB，而且轮廓那 66.7% 完全不受材质影响。细节法线在 45% 档
已经略降 PSNR，29.38% 档降得更多；把同一张图降到 256² 也只回到 39.49 dB，说明问题不是
纹理分辨率或高频噪声，而是 LOD 表面点与高模参考像素已经不是同一个点。POM 在正视时
没有可见变化，符合“只有掠射角才有视差位移”的预期；它在 `aiLodCompensated.mat` 中已与
AO、细节法线共用 `compensationStrength` 总闸门，默认 `pomStrength=0` 之外仍需显式给
`--detail-height` 才会启用。

同时修正了一个会误伤生成顶点的检查：QEM 折叠产生的新顶点 UV 可能是 chart 角点的重心
插值，落在 `[0,1]` 外几个千分点。原来的 1e-3 容差会让整张细节法线/高度图拒绝烘焙
（monkey 29.38% 档实际越界 0.0008–0.0094），现在按 **2% 图集容差** 判断，真正平铺或
换 wrap 的 UV（例如 ×3）仍会被拒绝；光栅器本身只覆盖纹理范围，不会采样到图外。

**UV 空间 AO 贴图（新增，实测）**：顶点 AO 的上限是 LOD 顶点密度。为了捕捉比顶点更细的
腔体，`AmbientOcclusion` 新增 `bakeAmbientOcclusionMap()`：按源 UV 三角形光栅化，在每个
覆盖 texel 上用 BVH 做余弦半球可见性采样，再向 chart 外扩 4 texel，输出单通道 R8。
`mmgeo --bake-ao-map N` 写 `ao-map.png`；`mm_bench --ao-map-size N` 运行时烘焙，
`--ao-map file.png` 读取离线结果，材质 `samples/materials/aiBakedAoMap.mat`，UI 有
“Baked AO map” 滑杆。它和顶点 AO 共用 `--ao-samples`/`--ao-radius`。

monkey 512×512、32 samples：覆盖 **151,190** 个 texel（57.7% 的图），均值 **0.914**、
最小 0.000，烘焙 **0.57–0.63 s**，R8 纹理 256 KiB（含 mip 约 341 KiB）。UV 越界或平铺
布局（torus、cloth）会被拒绝并提示先做唯一化 atlas；这类资产继续用顶点 AO。

32-sample 的半球估计会在贴图上留下 texel 级随机噪点，双线性过滤也消不掉。默认
`smoothingPasses=1` 做一次 3×3 Gaussian，但只对 covered texel 求和，平滑完再做 4 texel
外扩，所以 chart 之间不会互相串色。monkey 44.99% 档的贴图 AO 从 **41.77 dB** 提到
**41.82 dB**，目视眼窝和鼻翼更干净。把源贴图从 512 提到 1024，同机位渲染 PSNR 为
**57.8 dB**（平均绝对差 0.0285/255），烘焙时间却从 **0.57–0.63 s** 涨到 **2.34 s**、
显存 4 倍；AO 是低频
信号，512 已经覆盖当前测试资产的腔体频率，继续加分辨率不是优先项。

`mm_bench --ao-map-size N` 在 `--ui`/`--dag` 路径烘焙的是高模源，在普通 headless 路径
烘焙的是传进来的那个 mesh。后者适合“直接给这个 mesh 补 AO”，但不能替代高模→LOD 的
源级烘焙；生产对比仍应先用 `mmgeo --bake-ao-map N` 生成 `ao-map.png`，再用
`--ao-map` 加载。

960×720、`--no-shadows`、monkey 7,084 面（44.99%）的三种参考系（PSNR / SSIM）：

| 参考（高模） | LOD 无 AO | LOD + 顶点 AO 0.5 | LOD + 贴图 AO 0.5 |
| --- | --- | --- | --- |
| 无 AO | **42.51** / 0.99540 | 40.45 / 0.99432 | 41.77 / 0.99376 |
| 顶点 AO 0.5 | 40.47 / 0.99424 | **43.17** / 0.99528 | 40.30 / 0.99267 |
| 贴图 AO 0.5 | 41.65 / 0.99380 | 40.23 / 0.99282 | **42.69** / 0.99507 |

结论有三条：

1. **AO 表达必须匹配**。参考用顶点 AO 时，顶点 AO 比贴图 AO 高 **+2.87 dB**；参考用贴图
   AO 时，贴图 AO 比顶点 AO 高 **+2.46 dB**。跨表达比较没有意义。
2. **同表达下贴图只小胜**。在 monkey 55%/45%/38% 三个 cut 上，贴图 AO 比顶点 AO 高
   **+0.04 / +0.06 / +0.08 dB**（CPU Lambert 复算为 +0.31 / +0.27 / +0.26 dB）。LOD 仍有
   7–8 千个顶点时，顶点插值已经足够密；贴图的价值主要在“源资产本来就用 UV AO 贴图”和
   更极端的 LOD，而不是无条件替代顶点 AO。
3. **对未开 AO 的高模参考，AO 是改外观而不是恢复外观**。这也解释了为什么 `aiCavity`
   屏幕空间腔体、细节法线在这个“保留源法线抽稀”的管线上都拿不到正收益；真正能同时改善
   轮廓和内部误差的仍是近细远粗、时域抖动累积和更细的几何。

**方向性可见性 / bent normal（新增，已验证生效）**：标量 AO 只回答“有多少光被挡”，
不回答“剩下的光从哪个方向来”。减面把凹槽的开口形状抹平后，环境光会从已经被删除的
几何方向照进来，这正是眼窝、鼻翼和耳廓看起来“发平”的原因。`AmbientOcclusion` 现在
复用同一批半球采样，把未被遮挡的方向按余弦权重累加，得到每个顶点的 bent normal；采样
按成对相反的方位角发射，完全可见的表面其 bent normal 精确等于几何法线，不会出现
Monte-Carlo 倾斜。重复位置的生成顶点仍然先焊接再平均，避免 LOD seam 上出现方向跳变。

数据打包进顶点色的 G/B（切线空间 xy，z 由 `sqrt(1-x²-y²)` 重建），R 继续保存标量 AO，
因此一个 `UBYTE4` 同时携带两种可见性，不增加顶点带宽。材质 `aiBakedAo` 把它写入
Filament 的 `material.bentNormal`：diffuse IBL 走方向性辐照度，
`specularAmbientOcclusion : bentNormals` 再用同一个方向做 cone-traced 高光遮挡。这里
有一个必须注意的顺序：**`material.bentNormal` 必须在 `prepareMaterial(material)` 之前
赋值**。`prepareMaterial()` 内部会把 bent normal 转到世界空间并缓存到
`shading_bentNormal`，之后再赋值只改返回结构体，对光照完全无效——本轮最初 0/1 强度
逐像素完全一致就是这个原因，修正顺序后才真正生效。

monkey 44.99% cut、1024×640、32 samples、自动半径 0.365：17,027 个顶点发生倾斜，
平均 **8.4°**、最大 **89.6°**。同一帧只切换 `--bent-normal-strength 0 → 1`：
平均绝对差 **0.15/255**、最大 **16/255**、117,400 个通道发生变化，PSNR **50.1 dB**；
差异集中在眼窝、鼻翼、耳廓等凹槽。把太阳光关掉（`--sun-intensity 0`）做 IBL-only
隔离，差值完全相同，证明变化来自方向性间接光而不是直射光。幅度不大是预期的：平均
倾斜只有 8°，而太阳光在默认对比里占主导；它的价值是让凹槽的环境光方向正确，而不是
替代几何。

但**它不是一个 PSNR 收益项**。同机位把 44.99% cut 与“也开了 bent normal 的高模参考”
相比：强度 0 为 **39.59 dB / 0.99436**，强度 1 为 **38.98 dB / 0.99300**。作为对照，
高模自身开/关 bent normal 的画面差为 mean 0.13/255、max 14，和 LOD 的 0.15/255、max 16
同量级——说明信号大小是对的，只是高模与 LOD 采样的是不同表面点，方向性变化无法逐像素
对齐。因此 `--bent-normal-strength` 默认 **0（opt-in）**，和细节法线、POM、cavity 一样
只在美术判断需要方向性环境光时打开；不要把它当作“减面后自动提升 PSNR”的开关。

新增对比旋钮：`--bent-normal-strength`（0 等价于旧的纯标量 AO）、`--ibl`、
`--ibl-intensity`、`--sun-intensity`；`--ui` 里有对应的 Bent normal / IBL intensity /
Sun intensity 滑杆，可以把太阳光拉到 0 只看着色补偿。限制同样明确：它只影响间接光
的 diffuse 与环境高光遮挡，补不了轮廓、薄几何、真实遮挡覆盖和几何位移；程序化 IBL
只是三阶 SH，真实资产应接自己的环境贴图。另外当前为了对比方便复用了顶点色，生产上
若资产已有顶点色，应改写到 `CUSTOM0`/独立 attribute，避免覆盖美术数据。

**极端档位诊断（torus 20%）**：质量门并没有“误杀”一个已经足够好的 334 面结果。torus
20% 目标（230 面）下，最接近的候选是 **334 面且焊接边界为 0**，但最大几何误差
`0.030999` 超过预算 `0.025108`（约 23%）；另一个 **446 面候选**几何误差
`0.024817` 已达标，却有 **566 条焊接边界而基准为 0**，是真实裂缝，因此被拓扑门拒绝。
在默认 UV 拆分实现下，UV 分歧不再触发拒绝；torus `--target-ratio 0.2` 当前实测仍停在
**550 / 1,152 = 47.74%**，closed、min quality 0.3228，剩余拒绝是 group topology 16 /
geometry 7。33.16% 是旧 UV 拒绝门版本的数字，不是当前下限。这两类剩余问题分别需要更好的
QEM 落点和跨缝重建，不能靠放松质量门解决。试过“局部误差最小落点”与
“预算超限后改选落点”两种策略，都会改变整条塌缩顺序，使 torus 退化到 43%–48%；
已回滚，保留原来的首个合法落点策略。

`test_manymesh` 现为 **75 passed + 1 skipped**（共 76 个用例），新增同一位置三份 chart
属性副本、同位置 divergent UV 拆分的 CornerSimplifier 回归，以及 LodGraph 端到端 3 副本
回归（build → select → compact → UV 岛检查）；原有的 UV AO 贴图覆盖、确定性、凹角变暗和
平铺 UV 拒绝回归全部
保留，接缝法线、强度混合、自动强度策略以及源网格 AO 的确定性、焊接和离表面吸附回归也
未回退；高度烘焙的“同几何全中性”“正负位移符号”和“平铺/超距拒绝”三个回归仍在。MSVC
Release 的 76 个用例本轮完整跑过（75 pass + 1 个 HTTP 用例因本地无服务端而 skip），
`mmgeo`、`mm_bench`、`manymesh` 均编译通过并完成了截图验证。

**抗锯齿能补回多少轮廓（新增 A/B）**：29.38% monkey 档（4,626 三角形）在 1024×640 下，
高模和 LOD 使用同一默认材质、同一机位。只给 LOD 开 MSAA 是不公平的，因此
两套图都开同样的 MSAA 后再比较：

| 方案 | PSNR | SSIM |
|---|---:|---:|
| 无 AA（参考/LOD 都关） | 39.76 dB | 0.99159 |
| MSAA 2×（参考/LOD 都开） | **40.87 dB** | **0.99221** |
| MSAA 4×（参考/LOD 都开） | **41.40 dB** | **0.99262** |
| TAA（参考/LOD 都开） | 37.92 dB | 0.99060 |

MSAA 2× 的 +1.11 dB、4× 的 +1.64 dB 来自轮廓像素的覆盖率平滑：它让 LOD 的边缘更接近
高模 MSAA 参考，但没有恢复被减面删掉的几何。目视仍能看到眼窝、鼻翼、耳廓和内耳轮廓变粗。TAA 在这个静态机位
反而下降，原因是历史反馈把边缘糊开并引入不匹配；本轮不把 TAA 当作补偿收益项。
`mm_bench --msaa 4` / `--taa` 可复现；2×2 对照图在
`out/shadecomp-monkey29/montage_msaa.png`。结论更新为：**着色补表面响应，MSAA 补边缘
覆盖率，几何轮廓本身仍只能靠质量门、近细远粗或更高密度的小三角形**。
移动端 4× MSAA 的带宽/填充成本明显高于桌面，建议先试 2× 或与动态分辨率配合；本轮没有
Android/iOS 真机，不能把桌面 MSAA 数据直接当成移动端结论。

**26.44% 档的着色饱和点（新增）**：monkey 4,162 面、960×720、固定机位、`--no-shadows`。
基线 **26.37 dB / 0.96480**。10°/auto 缝法线 PSNR 不变（26.37 dB），SSIM 提到
**0.96567**；顶点 AO 0.5 降到 **25.14 dB / 0.95846（-1.23 dB）**，目视在下巴和脸颊形成
块状暗斑；参考与 LOD 同开 4× MSAA 为 **26.39 dB / 0.96541**，再叠缝法线为
**26.38 dB / 0.96606**。该机位模型占画面更大，MSAA 的 PSNR 收益从 29.38% 档的
**+1.64 dB** 缩到 **+0.02 dB**，说明 AA 收益依赖屏幕覆盖率，不能跨机位复用数字。
结论：26% 档材质侧已经到顶，AO/细节法线/roughness 应保持关闭；保留缝法线改善 SSIM，
MSAA 按移动端预算选 2×/4×；轮廓、耳廓和眼窝的缺失只能靠几何质量门、近细远粗、阴影
代理或学习型重建。图在 `out/shade26/montage_26.png`，数据在
`out/shade26/shading.json`、`out/shade26/msaa.json` 和 `out/shade26/within.json`。

**38.00% 档的着色收益复测（新增）**：monkey 5,982 面，960×720，`--no-shadows`，高模与
LOD 使用同一材质，并且每组都与自己的匹配参考比较（无 AA 对无 AA、AO 对 AO、MSAA 对 MSAA）：

| 方案 | PSNR / SSIM | 相对收益 |
|---|---:|---:|
| 无 AA | 37.38 dB / 0.98135 | 基线 |
| 4× MSAA | **38.81 dB / 0.98342** | **+1.43 dB** |
| AO（同材质关闭补偿为 36.61 dB / 0.97843） | 37.33 dB / 0.98023 | +0.72 dB |
| AO + 细节法线 0.25 | 37.28 dB / 0.97999 | -0.05 dB |
| AO + 4× MSAA | 38.69 dB / 0.98240 | 低于单独 MSAA |

AO 在这一档会沿下巴和颈部的大三角形形成块状暗斑，细节法线只补回 1.69° 的平均法线差，
不足以抵消贴图重采样噪声；AO 与 MSAA 也不叠加。因此 38% 档应优先抗锯齿，AO 只在 45%
以上或完整 IBL 管线中按距离淡入，细节法线继续默认关闭。对照图在
`out/shadecomp38/montage_38.png`。

**同机位 38% 复验（新增）**：上表的自动取景会改变模型在画面中的尺寸，不能跨批次直接
比较 PSNR。固定同一相机、960×720、`--no-shadows`，用 `--dag --savings 0.62` 选到
5,982 面（38.00%）重测：

| 方案 | PSNR | SSIM |
|---|---:|---:|
| 无 AA | 41.81 dB | 0.99323 |
| 4× MSAA | **42.07 dB** | 0.99355 |
| 缝法线 10° / auto | 41.94 dB | **0.99383** |
| 4× MSAA + 缝法线 10° / auto | **42.17 dB** | **0.99401** |

在这一机位下，4× MSAA 为 +0.26 dB，缝法线修复为 +0.13 dB，两者叠加为 +0.36 dB；
排序仍是 **MSAA 主收益、缝法线小幅正收益、AO/细节法线负收益**。缝法线修的是
同位置重复法线在大三角形上的明暗断层，不增加三角形、也不改轮廓。UI 现在有
“Use measured preset for this cut”：保留率 <45% 时自动选 4× MSAA + 10°/auto 缝法线，
并关闭 AO、细节法线、POM 和 roughness 补偿；45%+ 时切到顶点 AO 0.5 + 10°/auto 缝法线。
`--auto-shading-preset` 和 UI 的 “Auto apply measured preset” 会在每次 cut 变化后自动
重跑同一判据，UI 手动滑杆仍可覆盖自动结果。自动档位只改着色/AA，不改变几何选择。
同一判据已下沉为 `recommendedShadingCompensationPreset(retainedRatio, hasCompensation)`，
位于 `manymesh/ShadingNormals.h`；`test_manymesh` 新增
`ShadingCompensationPresetFollowsTheMeasuredLadder`，覆盖 45% 阈值、无 AO 材质回退和
各档位的 MSAA/缝法线参数。

**几何落点：着色补不回的轮廓，先靠落点少丢（本轮新增）**：`CornerSimplifier` 不再按
QEM 成本返回第一个合法落点，而是同时评估 keep/remove 端点、中点、QEM 最优点、QEM
最优点在局部切平面上的投影、以及它在源三角形上的最近点。排序使用局部双向表面偏差
（被删源点到新三角形的距离 + 落点到源表面的距离）、落点到每个被改写三角形平面的
偏差、UV/normal 误差和重心外插量。这样避免两个问题：QEM 最优点落进薄壳内部；以及
落点在曲面上但偏离某个邻接三角形的平面，导致该 chart 的仿射 UV 被外插拉偏。现有
`test_manymesh` 72 项中 71 通过、1 项按环境变量跳过。

torus 1,152 面、同一 3/4 机位、960×720、`--no-shadows --msaa 4`，参考为原始高模：

| 变体 | 面数 / 保留率 | PSNR | SSIM |
|---|---:|---:|---:|
| 旧压力测试 cut | 338 / 29.3% | 31.86 dB | 0.98370 |
| 只按表面偏差排序（UV 外插偏大） | 382 / 33.2% | 31.12 dB | 0.97869 |
| QEM-first 基线 | 444 / 38.5% | 32.49 dB | 0.98693 |
| 表面 + 平面偏差约束（当前默认） | 452 / 39.2% | **33.89 dB** | **0.98773** |

结论：**着色策略能把表面响应和边缘覆盖率补回一点，但补不了轮廓、薄几何和接触关系。**
当减面进入 30% 区间，优先把顶点落点约束在源表面附近，而不是为了少几十个三角形把
几何拉离表面；后者在 3/4 机位会损失约 2.4 dB，且 MSAA/接缝法线的 +0.3–0.4 dB 无法
抵消。当前默认相对 QEM-first 在面数只多 1.8% 的情况下提高 **1.40 dB / 0.00080 SSIM**；
更严格的平面权重可以把 torus 推到 474 面 / 34.29 dB，但默认选 0.5 权重的折中点。
目视上 338/444 的环体左上有一处可见的平切凹口，452 默认结果已经消失。对照图见
`out/torus-lod-montage-final.png`。

同一落点策略在另外两类资产上做了 DAG 同路径复验（参考与 LOD 都走 `--dag`，避免直接
加载 PLY 与运行时 DAG 的材质/光照差异污染指标）：monkey 6,928 面 / 44.00% 档在
10°/auto 缝法线下从 **43.28 → 43.39 dB**（SSIM 0.99511 → 0.99549）；cloth 36,036 面 /
48.06% 档从 **40.74 → 40.78 dB**（SSIM 0.99046 → 0.99083）。两例的边界边数量不变，
non-manifold/duplicate/flipped 仍为 0。着色补偿是稳定正收益，但只有 0.04–0.11 dB：
它能修接缝和 shading discontinuity，不能消除 cloth 大三角形造成的块状起伏，更不能
恢复被减掉的轮廓。因此生产策略仍是几何质量门优先，AA 和法线修复作为廉价后处理，
AO/细节法线/POM 只在中高档或资产确有对应细节时开启。

---

### 7.10 M4 首个切片：几何分配在重建回路里（负结果）

M4 的原始假设是：**重建能力应该反过来决定几何预算**。要验证它，第一步不是训练一个
联合模型，而是回答一个更便宜的问题：在总三角形预算固定时，**把三角形放在哪里**会
不会改变重建后的画质排序？如果不会，联合优化就没有可优化的自由度。

**工具**：`tools/m4alloc/run.py`。它把同一预算分配给两种策略：

- **uniform**：`selectLodGraphAtRatio`，所有 cluster 按同一比例减面。
- **distance**：`selectLodGraph` + 固定屏幕空间误差阈值，近/误差大的区域更细。

脚本逐视角渲染（`mm_bench` 一次只报告当前视角的 cut）、用二分把 distance 的阈值校准
到 uniform 的实际面数、再用同一个 tiny 网络（同种子、同迭代数、同一验证划分）分别
训练。`--ignore-ceiling` 让 uniform 真正到达目标比例。

#### 7.10.1 单物体没有分配自由度

monkey，640×360，8 个方位角，budget 35%：

| 策略 | 面数 | 实际比例 |
|-|-|-|
| uniform（`--savings 0.65`） | 5,504 | 34.96% |
| distance（校准后 17.78 px） | 5,130 | 32.58% |

两条策略的面数差了 6.8%，但更关键的是：**把 uniform 调到 0.326（5,130 面）或
0.379（5,966 面）后，两种策略的输出逐像素完全相同**（RGB max diff = 0）。单物体
位于画面中心、所有 cluster 深度接近时，屏幕误差选择器和比例选择器会落到同一个 DAG cut。
这不是实现巧合，而是 DAG 层级离散：阈值在平台内移动不会换层，比例二分也只是在找
同一个平台。

同一批数据上：

| budget | 策略 | 面数 | 双三次 | tiny | tiny 增益 |
|-|-|-|-|-|-|
| 35% | uniform | 5,504 | 38.98 dB | 38.98 dB | +0.00 |
| 35% | distance | 5,130 | 38.32 dB | 38.34 dB | +0.01 |

> **结论一：单物体基准测不了 M4。** 没有深度差异，就没有“近细远粗”可分配的东西；
> 两种策略在等面数下是同一个 cut。此前把单物体上的 LOD 差异当作“分配策略差异”的
> 任何解读都是错的。M4 必须使用有深度变化或视锥外几何的场景。

#### 7.10.2 深度排序场景：uniform 仍然更好

三实例行：3 个 monkey 沿 z 排开，总 47,232 面，相机位于近端；4 个视角、±20° 方位角、
640×360：

| 策略 | 面数（4 视角中位） | 双三次 | tiny | tiny 增益 |
|-|-|-|-|-|
| uniform | 16,532 | **38.52 dB** | **38.57 dB** | +0.05 |
| distance（8.66 px） | 16,300 | 37.96 dB | 38.00 dB | +0.04 |

这次两种分配的输出确实不同（0.03–0.46% 像素有差异），面数也接近（差 1.4%），
但 **uniform 仍然高 0.56 dB**。distance 在近端/高误差区域多花三角形，代价是远端和
低误差区域被压得更粗；在这条深度范围只有约 5.5–9.5 个单位的行上，后者的损失更大。

> **结论二：按几何误差分配不是免费收益。** 屏幕空间误差只描述“几何差多少”，不描述
> “重建能不能补回来”。在 38.5 dB 的画质上，tiny 网络只加 **+0.04~0.05 dB**，说明
> 网络几乎没有 headroom；因此重建后的排序与重建前一致，M4 的“联合”没有发生。

**质量下限处再次退化。** 把目标压到 20% 时，默认质量门把 uniform 停在 **15,050 面
（31.86%）**；distance 校准到同一面数后，两者**逐像素相同**（RGB max diff = 0），
双三次/tiny 都是 **37.36 / 37.39 dB（+0.03）**。也就是说，DAG 最粗的合法 cut 是唯一的，
两种分配在质量下限处没有第二个选择。可比较的分配差异只存在于中间预算（如 35%），
而那里 uniform 反而更好。

> **结论三（对 M4 的修正）：** 当前最需要补的不是更聪明的分配权重，而是一个**网络真正
> 有 headroom 的低预算档**。当粗几何本身还有 33–35 dB 时，网络能加 0.5–1 dB，分配策略
> 的差异才有机会被重建放大或反转。35% 以上的预算对 monkey 这种资产已经接近“几何问题
> 不重要”的区间，不适合做联合优化实验。
>
> 低预算复验（§8.9）确实把网络增益从 **+0.05 提到 +0.50 dB**，但同一档位上时域历史对
> PSNR 是 **−0.12**。所以“网络有 headroom”是成立的，“用重建能力换几何预算”仍然没有
> 成立；下一步要么换一个重建先验更强的模型，要么换误差结构不同的资产（扫描模型、
> 强运动序列），而不是继续调分配权重。

**复现**：

```shell
python tools/m4alloc/run.py --mesh assets/models/monkey/monkey.obj \
    --out out/m4-monkey --ratios 0.35 --views 8 --iterations 2000
python tools/m4alloc/run.py --mesh out/m4-scene/row.obj \
    --out out/m4-row --ratios 0.35 --views 4 --view-span 40 \
    --eye 0,0.3,3.5 --target 0,0,-2 --iterations 2000
```

---

## 8. 相关工作：移动端别人怎么做，以及由此对本方案的修正

### 8.1 移动端神经超分的现状

| 方案 | 性质 | 输入 | 成本 |
|-|-|-|-|
| **Arm NSS**（SIGGRAPH 2025） | 学习式**时域**超分，跑在 Arm GPU 的神经加速器上 | 低分颜色、**历史颜色**、**运动矢量**、深度、抖动、相机矩阵、**上一帧隐状态张量** | 540p→1080p 约 **4 ms**，约 10 GOPs，INT8 |
| **Qualcomm GSR** | **非神经**的手写空间超分，单 pass | 仅当前帧颜色 | 极快，不需要运动矢量 |
| **Mob-FGSR**（SIGGRAPH 2024，浙大/OPPO/UCSB） | **运行时无神经网络**：MLP 离线训练 → 烘焙成 **LUT** 查表；帧生成 + 超分 | **只有颜色、深度、运动矢量**（不用 G-buffer） | 帧生成 ~1.9–2.2 ms，超分 ~1.66 ms，**已进商业产品** |
| AMD FSR 2 / DLSS | 时域超分 | 颜色 + 历史 + 运动矢量 + 深度 | FSR2 时域版**尚不适用于移动端** |

**NSS 的架构值得注意**：4 层 UNet + skip，但输出的是**参数预测**——每像素一个 4×4 滤波核、
时域系数，以及传给下一帧的**隐状态**。训练用**循环式**（前向跑约 100 帧再反传），
损失同时惩罚空间锯齿与时域闪烁；还有历史拒绝掩码处理遮挡。也就是说：
**参数预测 + 时域累积**是移动端目前的答案。

### 8.2 移动端几何虚拟化的现状

| 方案 | 内容 |
|-|-|
| **腾讯 NanoMesh**（SIGGRAPH） | 轻量级移动端 cluster LOD：离线层次化 cluster 构建 → 运行时流式加载/剔除/光栅化 + visibility buffer；**移动端 8000 万面场景**。是本课题 M2 最直接的先行工作 |
| **Arm Mali + UE Nanite** | Nanite 已能在 Mali 上跑；一棵 63 万面的树 **5 FPS → 38 FPS**。Arm 指出 TBR 架构顶点吞吐低，所以剔除的价值很大；但 **HSR（隐藏面消除）会削弱 Z 剔除的收益** |
| **Adreno 的约束**（Vulkanised 2026） | visibility buffer 在 Adreno（尤其 600 系）不实用；descriptor indexing 慢；**逐三角形剔除相对硬件 binning 可能得不偿失**（LRZ） |

### 8.3 由此对本方案的四条修正

> **① 最大的差距：M3 缺时域。** 上面每一个能上移动端的方案（NSS、DLSS、FSR2、Mob-FGSR）
> **都是时域的**。我们目前的 M3 是**单帧空间**重建，这就是为什么只拿到 +2.0 dB，
> 而 NSS 能做到接近 DLSS2 的画质。**颜色历史 + 运动矢量的累积才是画质的主要来源**，
> 不是更好的空间网络。这是下一阶段最该补的一块。

> **② 「核预测是错的工具」这个结论要加限定。** NSS 用的正是参数预测（4×4 核 + 时域系数）。
> 我那边 KPN 失败的真正原因是：**把空间滤波核用在单帧上，它只能模糊**；
> 而在时域流水线里，预测出的核是用来**累积历史**的，能真正恢复细节。
> 所以不是核预测不对，是**没有时间的核预测**不对。

> **③ 误差图的冗余是意料之中的。** Mob-FGSR **只用颜色、深度、运动矢量**，
> 连 G-buffer 都不用，就已进商业产品。整个领域收敛到的信号是**时域量（运动）+ 深度**，
> 而不是表面/误差类 G-buffer。我们的误差图没有时域成分，价值低是可以预期的。
> 若要它有用，方向是**时域的误差**（例如这一帧的降面误差相对上一帧如何变化），
> 而不是更精细的空间误差图。

> **④ 移动端 TBR + HSR 让几何那一半更重要——这对我们是好消息。**
> 移动 GPU 是分块渲染 + 隐藏面消除，片元相对便宜，顶点吞吐反而是瓶颈
>（Arm 原话：TBR 架构顶点吞吐低）。我在桌面核显上测出「分辨率几乎不影响帧时」
> 是 IMR 的行为；**在移动端，几何压缩的相对收益会比桌面更大**。

> **⑤ 部署路线可以更务实。** Mob-FGSR 的做法是**离线训练、运行时查 LUT，完全没有神经网络推理**——
> 因为要适配没有光流硬件、算力有限的现成手机。我们的 M3 如果要落到移动端，
> 这条路线（把训练好的小网络烘焙成 LUT / 或极低比特量化）比直接跑网络更现实。

---


### 8.4 时域切片：做到哪一步，以及一个方法论更正

按 §8.3① 的结论动手做了时域。`mm_bench` 加了 `--jitter N`：同一机位渲染 N 个**亚像素偏移**
的子帧（Halton 序列），这正是 DLSS/FSR2/NSS 里时域累积所依赖的信息来源。

**等分辨率下的时域累积（6 视角数据集的 2 个验证视角，无学习）：**

| 累积帧数 | 1 | 2 | 4 | 8 |
|-|-|-|-|-|
| 朴素平均 PSNR | 33.15 | 33.60 | 33.81 | **34.07 dB** |

**只是把 8 个抖动帧平均，就白拿 +0.92 dB**，6 个视角全部单调。

**学习式对照**（tiny，2000 次迭代）：

| 输入 | 朴素 | 学习式 |
|-|-|-|
| 1 帧 | 33.15 | **34.35** |
| 4 帧 | 33.81 | 34.60 |
| 8 帧 | 34.07 | 34.39 |

> **观察：学习式单帧（34.35）已经比朴素单帧（33.15）高 1.2 dB；再叠加更多帧只多约 0.2 dB。**
> 因为**这个设置没有"采样赤字"**——目标分辨率与渲染分辨率一样高，抖动只在亚像素级，
> 没有真正缺信息。DLSS/NSS 是 540p→1080p（每输出像素只有 1/4 个样本），时域累积在那里
> 才是决定性的。

**② 一个必须记录的方法论更正。**

上面 scale 2 的实验原本是用「把 640×360 渲染缩放到 320×180」来模拟低分辨率。**这是错的**：

| 320×180 的来源 | bicubic 升到 640×360 的 PSNR |
|-|-|
| **原生渲染**（每像素 1 个样本） | **28.33 dB** |
| 从 640×360 **缩放**而来 | **30.12 dB** |

缩放本身已经把 4 个样本平均掉了，**等于已经超采样**，根本不是低分辨率渲染。差 **1.8 dB**。

> **推论：本文档此前所有 scale 2 的数字（包括 bicubic 基线 30.59 dB）都偏乐观**，
> 不反映真实的低分辨率渲染；而且用缩放近似**根本测不出时域累积的效果**
>（实测只有 +0.06 dB，而原生低分辨率下是 +0.35 dB 且单调）。

**原生低分辨率下的时域累积**（320×180 原生渲染，7 个抖动帧，v00 单视角）：

| 累积帧数 | 1 | 2 | 4 | 7 |
|-|-|-|-|-|
| bicubic 升采样 PSNR | 28.33 | 28.49 | 28.62 | **28.68 dB** |

> **这个实验没跑完**：只完成了 6 个视角中的 1 个。原因是**本机当时被远程桌面等任务占满**
>（ToDesk 累计 7568 秒 CPU），320×180 的渲染每张要 2 分钟。继续跑会和你的工作抢机器，
> 所以主动停下。**这是下一步最该补的实验**：6 个视角 × 8 个抖动帧的原生低分辨率数据，
> 再训一个时域模型，与"单帧 bicubic"和"朴素累积"对比。

---

### 8.5 原生低分辨率 + 时域累积：M3 目前最好的结果

按 §8.4 的更正，用**原生渲染的 320×180**（每像素 1 个样本，不是缩放来的）重做了一遍，
这是真正的「低分辨率渲染 + 时域累积」设置。6 个视角，4 训练 / 2 验证，tiny 模型，
2000 次迭代；下表是 2 个验证视角上的中位。

| 配置 | PSNR | SSIM | 相对朴素单帧 |
|-|-|-|-|
| 朴素 bicubic，单帧 | 30.33 | 0.9629 | —— |
| 朴素 bicubic，**平均 8 帧** | 31.11 | 0.9668 | **+0.78** |
| 学习式，**单帧** | 31.21 | 0.9672 | **+0.88** |
| 学习式，**8 帧** | **31.68** | **0.9707** | **+1.35** |

> **关键结论：学习和时域累积是互补的，收益可以叠加。**
> - 只加学习：+0.88 dB
> - 只加时域累积：+0.78 dB
> - 两者都有：**+1.35 dB**（学习式 8 帧比学习式单帧还高 +0.47，比朴素 8 帧高 +0.57）
>
> 这正是 §8.3① 从文献得出的判断，现在用我们自己的数据证实了：**DLSS 类的方案
> 之所以是「学习 + 时域」，是因为这两条腿各自独立地贡献画质**。

> **这比之前的时域实验说明了更多**：§8.4 里等分辨率（无采样赤字）时叠加帧几乎无增益
>（+0.2 dB），而**这里 2× 上采样、有真实采样赤字时，时域累积贡献了 +0.78 dB**。
> 印证了「时域累积的价值随采样赤字增长」。

**局限**：只有 4 个训练视角、2 个验证视角、单一随机种子、模型很小（2 万参数）。
绝对数值只作指示，可比的是同一批数据内的相对差值。

---

### 8.6 真时域：运动补偿的历史

§8.5 的「时域」其实是**同一机位的多帧堆叠**，没有真实运动。真实时域必须处理**历史帧对齐**。

这里用一个省算力的设置：**纯相机旋转（pan）**。纯旋转**没有视差**，像素位移只取决于旋转、
与深度无关，因此对应关系可以**解析精确计算，不需要深度缓冲**。`mm_bench --pan D` 渲染这
样的序列（机位不动、视线扫过 D 度），`tools/mmtemporal/temporal.py` 做重投影 + 混合。

**结果**（12 帧、3° pan；320×180 原生渲染 → 640×360；朴素指数混合，无学习）：

| 配置 | PSNR（第 1–11 帧中位） |
|-|-|
| 粗几何单帧 | 28.27 dB |
| 混合历史，**不重投影** | **26.91 dB** |
| 混合历史，**正确重投影** | **28.93 dB（+0.66）** |

> **关键：运动补偿不是优化项，是「有没有用」的分水岭。**
> 不对齐就直接混合，会因**鬼影**比单帧还差 1.36 dB；把旋转重投影算对，同样的混合就变成
> +0.66 dB 的增益。这也是时域方案最典型的失效模式。

**还没做**：把这里的朴素混合换成一个**学习式时域模型**（输入当前帧 + 重投影历史 + 运动矢量），
以及递归的**历史缓冲**（当前每帧只依赖上一帧，还没有 rejection 掩码处理遮挡）。这是
与 NSS/Mob-FGSR 对齐的最后一步。

---

### 8.7 学习式时域 + 历史拒绝

把 §8.6 的朴素混合换成网络：输入「当前粗帧 + 重投影历史」两个 3 通道图像，输出全细节帧。
数据由 `temporal.py --export` 导出成训练三元组，`mmtrain --stack 2` 直接读。

**同样两帧上的对照：**

| 配置 | PSNR | 相对粗几何 |
|-|-|-|
| 粗几何单帧 | 28.26 | —— |
| 朴素 50/50 混合历史 | 28.93 | +0.67 |
| 学习式，仅当前帧 | 29.56 | +1.30 |
| **学习式，当前 + 重投影历史** | **30.18** | **+1.92** |

> **学习式时域比朴素混合高 +1.25 dB。** 说明历史不是简单地"平均进去"就有用——
> 网络学会了**按内容决定该从历史里取多少**，而固定 0.5 权重做不到。

**历史拒绝（rejection）的意外结果：**

| 颜色裁剪阈值 | 时域增益 |
|-|-|
| 不拒绝 | **+0.65 dB** |
| 0.05 | +0.02 |
| 0.10 | +0.07 |
| 0.20 | +0.21 |

> **颜色裁剪在这里是有害的，与降噪文献的直觉相反。** 原因是：纯旋转下历史几乎处处有效
>（没有遮挡），而「历史与当前帧的色彩差异」**恰恰就是我们要平均掉的几何误差本身**。
> 在蒙特卡洛降噪里，这个差异是噪声，应当剔除；在**几何误差重建**里，它是**信号**，
> 剔除等于把要累积的东西扔掉。有效性掩码（重投影落在画面外）一直开启，已在基线内。

> **局限**：纯旋转没有真正的遮挡（无视差），所以这里只能验证有效性与颜色裁剪；
> 真正的 disocclusion 需要相机**平移**加深度缓冲，属于后续工作。

---

### 8.8 更多数据下的复现

§8.7 只有一段序列（11 个样本），结论有过拟合风险。扩到 **4 段序列 × 8 帧**（4 个方位角，
每段 3° pan；28 个训练三元组，4 帧验证）：

| 配置 | PSNR | SSIM | 相对粗几何 |
|-|-|-|-|
| 粗几何单帧 | 31.09 | —— | —— |
| 朴素 50/50 混合历史 | 32.04 | —— | +0.95 |
| 学习式，仅当前帧 | 31.79 | 0.9739 | +0.70 |
| **学习式，当前 + 重投影历史** | **32.61** | **0.9779** | **+1.52** |

> **结论在更多数据上复现**：学习 +0.70、时域 +0.95、合计 **+1.52 dB**。
> 学习式时域比朴素混合高 **+0.57 dB**——比单序列时的 +1.25 更保守，因为单序列时是过拟合。
> 这个更小的差值才是可信的。
>
> 另外，朴素时域在 32 帧上的中位增益是 **+0.85 dB**，与 §8.5 的 +0.78 一致。

**仍然偏小的统计**：28 个训练样本、4 帧验证、单一随机种子。要写进论文还需要数量级更多的
数据（多场景、多相机轨迹），而这受限于本机渲染吞吐（见 §8.4 的记录）。

---

### 8.9 真视差：平移序列、深度重投影与遮挡拒绝

§8.6–8.8 的「真时域」其实是纯旋转：没有视差，也就没有真正的 disocclusion，历史拒绝
只能验证「颜色裁剪有害」。这一轮补上了真正的平移。

**数据链路**

- `mm_bench --translate D --frames N` 让相机沿视线右方向平移 D 个世界单位，跨 N 帧；
  相机和目标一起平移，视线方向不变。`--frames` 与 `--jitter` 分开，避免亚像素抖动
  改变高模目标相机的采样位置。
- `mm_bench --camera-out <file>` 写出每一帧精确的 eye/target/FOV/分辨率。深度和重投影
  都读这份文件，而不是在 Python 里重新推导相机路径——半像素的偏差会表现为鬼影，
  很难和重投影 bug 区分。
- 新增 `tools/mmdepth`：按同一份相机列表把粗网格光栅化成 view-space 深度
  （`MMDEPTH1`，float32）。Filament 公共 API 不暴露深度附件读回，所以这里用 CPU
  光栅化生成与渲染完全同机位的深度。
- `temporal.py --cameras ... --depth-dir ...` 用当前帧深度重建每个像素的世界位置，
  投影到上一帧相机采样历史；同时采样上一帧深度，深度不一致（相对误差 >5%）就判为
  disocclusion 并拒绝历史。

**设置**：monkey，粗网格 7,074 / 15,744 面（44.93%），4 个方位角 × 8 帧，
原生 160×90 → 640×360，总平移 0.6 个世界单位（相机距离约 3.25），`--no-shadows`。

**朴素混合**（固定权重）：

| 混合权重 | 重投影 | 深度拒绝 | 历史拒绝率 | PSNR | 相对粗帧 |
|-|-|-|-|-|-|
| 0.10 | 有 | 有 | 3.0–8.6% | 34.48 | −0.03 |
| 0.25 | 有 | 有 | 3.0–8.6% | 34.17 | −0.34 |
| 0.25 | 有 | 无 | 0% | 34.10 | −0.41 |
| 0.50 | 有 | 有 | 3.0–8.6% | 32.52 | −2.00 |
| 0.75 | 有 | 有 | 3.0–8.6% | 29.50 | −5.01 |
| 0.50 | **无** | — | — | 27.37 | −7.14 |

> **结论一：运动补偿仍然是分水岭。** 不对齐直接混合掉 7.14 dB；同样的混合加上深度
> 重投影只掉 2.00 dB，相当于挽回 **+5.14 dB**。这是平移场景下对 §8.6「重投影不是优化项」
> 的独立复现。

> **结论二：正确重投影不等于朴素累积一定有用。** 在 4× 上采样 + 45% 粗几何的设置里，
> 固定权重越大越差：历史经过双线性重采样后比当前帧更糊，平均进去会把当前帧的高频
> 细节一起拉低。最好的固定权重（0.10–0.25）也只是接近中性。这与纯旋转的 +0.66 dB
> 不矛盾：那里是 2× 上采样、几何更细，历史模糊的代价更小。

> **结论三：深度拒绝是可测量的，但幅度取决于运动。** 同一 0.25 权重下，开启深度
> 拒绝从 −0.41 提到 −0.34 dB（+0.07），拒绝 3.0–8.6% 的有效历史。平移越大，disocclusion
> 比例越高，这一项才会变得重要。它验证了掩码本身正确，而不是一个可以忽略的开关。

**学习式时域**（同一批 28 个训练三元组，2 个验证视角，tiny，2000 次迭代）：

| 配置 | PSNR | SSIM | 相对粗帧 |
|-|-|-|-|
| 粗几何单帧 | 34.51 | — | — |
| 学习式，仅当前帧 | 35.39 | 0.9838 | +0.88 |
| **学习式，当前 + 重投影历史** | **35.54** | 0.9832 | **+1.03（比单帧 +0.15）** |

> 网络把朴素混合丢掉的画质拿了回来，但历史只额外贡献 **+0.15 dB**，小于纯旋转的
> +0.57 dB。原因有两层：平移产生了真实的 disocclusion，历史并非处处有效；同时 4×
> 上采样下当前帧本身的信息缺口更大，网络更多是在补分辨率而不是补历史。
> SSIM 在堆叠历史上略低（0.9838 → 0.9832），说明 PSNR 的小幅收益伴随轻微的时域平滑。

**低预算复验（26.44%）**：同一序列换成 4,162 / 15,744 面的粗网格（质量门在
`--target-ratio 0.2` 下的下限）：

| 配置 | PSNR | SSIM | 相对粗帧 |
|-|-|-|-|
| 粗几何单帧 | 33.96 | — | — |
| 朴素 0.50 混合，重投影 | 32.30 | — | −1.65 |
| 朴素 0.50 混合，不重投影 | 27.23 | — | −6.72 |
| 学习式，仅当前帧 | **34.46** | 0.9807 | +0.50 |
| 学习式，当前 + 重投影历史 | 34.34 | **0.9842** | +0.38（比单帧 −0.12） |

> **结论四（与 45% 档相反）：** 几何更差时，历史没有变得更有用；PSNR 上它从
> **+0.15 翻成 −0.12**，只有 SSIM 提高（0.9807 → 0.9842）。也就是说，网络在低预算下
> 更依赖当前帧的合成先验，历史带来的平滑在这里是负担。**“时域重建可以换取更低几何
> 预算”在本数据上没有成立**，不能作为 M4 的正向证据。

**仍未做**：递归隐状态（当前模型是单步前馈，历史缓冲由 `temporal.py` 递归累积）、
把深度/运动矢量作为网络输入通道（目前只用于重投影）、以及长序列上的时域闪烁指标。

---

## 9. 为什么这个方案优于「移动端 Nanite」

- 不需要复刻 UE 级 Nanite
- 不依赖 NVIDIA 硬件（DLSS 不可用）
- 可以基于 Filament 落地（开源、跨平台、已有 Android 支持）
- 有明确的 baseline 对比
- 有 AI 元素
- 与「MegaLights：采样 + 重建」的研究思路一致

技术路线也符合当下实时渲染的发展方向：
**把不可承受的计算复杂度转化为可控制的近似误差，再用重建技术补偿。**

---

## 10. 开发环境与构建（当前状态）

### 9.1 仓库形态

本仓库是 **Google Filament** 的完整源码快照（含 vendored `third_party`），
作为 ManyMesh 的渲染底座。上游对应提交：`4bcb2e4e5aa2fdba45b0db73dcb92f5dbfc38752`。

为节省磁盘与带宽，本仓库采用 **blobless partial clone + sparse-checkout**，
工作区**不包含**以下目录（它们是完整上游内容的一部分，需要时可单独取回）：

```text
third_party/dawn      # WebGPU 后端依赖，约 517 MB（本课题用不到；根 CMakeLists 默认不构建）
docs / docs_src       # 文档站点与图片
art                   # 设计稿源文件
```

需要时恢复：

```bash
git sparse-checkout add third_party/dawn     # 或
git sparse-checkout disable                  # 取回全部
```

### 9.2 本机环境

| 组件 | 版本 / 位置 |
|-|-|
| CPU / RAM | Intel 12 代（20 线程）/ 16 GB |
| GPU | Intel Iris Xe（核显） |
| Visual Studio | 2022（MSVC 19.38.33145），`D:\visual studio 2022` |
| CMake | 3.31.6（VS 自带） |
| Ninja | 1.12.1（VS 自带） |
| Python | 3.12.3（Anaconda） |

> **注意：** Filament 不支持 MSYS2 环境（`CMakeLists.txt` 会检测 `MSYSTEM` 环境变量并
> 直接报错）。在 Git Bash 中调用 `cmd` 构建时，必须先把 `MSYSTEM` 清空。

### 9.3 构建（Windows 桌面）

Filament 官方在 Windows 上**不使用** `build.sh`（它面向类 Unix 环境），而是直接用
VS 原生工具链 + CMake。构建目录 `out/` 已被 `.gitignore` 覆盖。

```bat
:: 相当于：x64 Native Tools Command Prompt 下的操作
call "D:\visual studio 2022\VC\Auxiliary\Build\vcvars64.bat"

cmake -S . -B out\cmake-release -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DFILAMENT_BUILD_TESTING=OFF

ninja -C out\cmake-release -j 10 filament          :: 核心引擎
ninja -C out\cmake-release -j 10 material_sandbox  :: 可运行样例
```

产物：`out/cmake-release/filament/filament.lib`，工具 `tools/matc/matc.exe`、
`tools/cmgen/cmgen.exe`、`tools/resgen/resgen.exe`。

### 9.4 仓库本地配置（已设置，仅作用于本仓库）

这些是**仓库级**（非全局）配置，不会影响机器上其它项目：

| 配置 | 值 | 原因 |
|-|-|-|
| `http.proxy` | `http://127.0.0.1:7890` | 直连 GitHub 会被间歇性阻断 |
| `core.autocrlf` | `false` | 保证工作区与对象库字节一致 |
| `core.sparseCheckout` | `true` | 排除上述大体量无关目录 |

### 9.5 已知构建修补（MSVC 专有）

上游该快照在 MSVC 上有一处编译缺陷：`FRenderer` 持有
`std::unique_ptr<TextureCache>`，而 `TextureCache` 仅有前向声明；
MSVC 会在 `FramePacer` 的两个 TU 中实例化其析构函数，触发
`error C2338: can't delete an incomplete type`（Clang/GCC 不触发）。

修复方式是在这两个文件中补上完整类型头：

```text
filament/src/FramePacer.cpp
filament/src/details/FramePacer.cpp
    +#include "TextureCache.h"
```

---

## 10. 当前实现状态（2026-10）

### 10.1 已完成

- **几何简化**：cluster 内与 cluster group 内均支持属性感知 QEM；corner 模式按三角形角点
  跟踪法线/UV，允许 UV/normal seam 内部折叠，并可用 QEM 最优位置生成新顶点。
- **Seam 与拓扑**：按精确焊接位置锁定 leaf 共享顶点；cut 组装按焊接位置去重，能够清理
  不同节点或同节点不同 UV 顶点产生的重合面。视觉回归中 torus/monkey/sphere/cloth 均未
  出现新增 boundary、non-manifold、duplicate、degenerate 或 flipped 三角形。
- **层次 DAG**：cluster chain + group merge + 单成员 chain（root 后继续降面）；
  --target-ratio 会选最接近预算且通过质量门的 cut。
- **运行时**：CPU cut、分页流式缓存、异步预取、HTTP Range fetcher（Windows WinHTTP，其他平台 CivetWeb）、
  间接绘制命令生成、编辑器滑杆/档位/近细远粗开关；DAG cut 的连续索引区间会合并成
  一个 draw，也可用 `--compact-cut-indices` 把当前 cut 的索引按材质压成一个 buffer。
- **顶点内存**：`compactLodSelection()` 现在同时压缩 source 与 generated，只保留当前
  cut 实际引用的顶点并重写索引；monkey balanced cut 从 22,268 降到 7,516（33.8%），
  torus 从 1,706 降到 502（29.4%），sphere 从 10,647 降到 2,019（19.0%）。压缩路径与
  全量路径截图逐像素一致。流格式 v4/v5/v6 均可读取，v4 会回退到 `positionSource`。
- **锁掩码构建**：`buildLockedMaskContext()` 之前对每个简化单元扫描整个网格的顶点；
  现在只扫描该单元实际引用的 source 顶点，输出逐位不变。cloth DAG 从 17.2s 降到 10.3s，
  monkey 从 3.9s 降到 2.1s，lock-mask build 从 9.5s 降到 0.37s（cloth）。
- **GPU 原型**：`tools/mmgpu` 在真实 Vulkan 上执行 compute cut selection、GPU index/draw
  压缩、三 pass GPU 顶点压缩、`vkCmdDrawIndexedIndirect` 和 visibility buffer；draw 消费的
  vertex/index/indirect buffer 全部由 GPU 生成。cut、compaction 和 visibility 现在记录进
  同一个 command buffer，每帧只有一次 `vkQueueSubmit` 和一次 `vkQueueWaitIdle`；torus
  640x360、2 px 阈值下，五次帧的 warm 平均提交等待从原来三次提交合计 **2.56-3.01 ms**
  降到 **1.24-1.42 ms**，GPU timestamp 为 cut 0.32-0.33 ms、compaction 0.05 ms、
  visibility 0.11 ms；`--legacy-submit` 可在同机复现旧的三次提交路径做 A/B。
  monkey 640x360 为 1.58 ms，cloth 320x180 为 5.38 ms（cut 3.68 ms）。阶段间用
  compute→compute 与 compute→graphics barrier 连接；mark pass 在 shader 内读取 cut 的
  实际压缩索引数，因此不需要阶段间主机回读。torus/monkey/sphere/cloth 四个模型上 GPU cut
  与 CPU 一致，压缩后的 source 顶点集合和三角形拓扑一致，visibility 重叠 100%、深度差异
  为 0；稠密顶点 ID 是并行 gather 产生的合法排列，不承诺与 CPU 逐位相同。Filament 后端
  `VulkanDriver::dispatchCompute`/`readBufferSubData` 已实现，`compute_test --api vulkan`
  在 Intel Iris Xe 上 2/2 通过（`out/cmake-vulkan` 构建）。
  **RenderDoc 单提交证据（本轮）**：`out/renderdoc-mmgpu/single_torus_capture.rdc/.xml`
  在 320x180、2 px 阈值下只有 **1 次 `vkQueueSubmit` / 1 次 `vkQueueWaitIdle`**，包含
  **4 次 compute dispatch**（cut + 3 个顶点压缩 pass）、**1 次
  `vkCmdDrawIndexedIndirect`**、1 个 render pass、3 次 image→buffer 回读和 7 个 barrier。
  barrier 覆盖 host→compute/indirect/vertex-input、compute→compute、compute→graphics 与
  graphics/transfer→host；host 上传和 compute 输出的目标阶段已从 `ALL_COMMANDS` /
  `ALL_GRAPHICS` 收窄到实际消费者。`mmgpu` 的退出码也改为使用 source 顶点集合 + 三角形
  拓扑契约，不再要求 GPU 并行分配的稠密顶点 ID 逐位相同；四模型单提交/legacy A/B 均
  以 exit 0 通过。

### 10.2 质量优先的下限

--target-ratio 是目标而不是保证。当前默认门控下，torus 的 `--target-ratio 0.2` 实测停在
**400 / 1,152 = 34.72%**，monkey 的 `--target-ratio 0.3` 停在
**4,712 / 15,744 = 29.93%**，`--target-ratio 0.2` 停在 **4,162 / 15,744 = 26.44%**；
剩余拒绝主要是 group topology/attributes，不再是 UV 平均或 QEM 落点。继续降低面数需要
更严格的质量门调优、跨缝重建或更强的小三角形预算，本实现没有通过放松质量门换面数。
同面数对照见 §7 的 corner 优先级条目：monkey 7,084 面对旧 7,124 面仍有 +0.89 dB PSNR
和 +0.00147 SSIM；属性 chart 选择修复后同 6,244 面为 27.10 dB / 0.97167 SSIM，
修复前为 25.24 dB / 0.92891。

### 10.3 尚未完成

- Filament **公共 API** 的常驻 compute + indirect draw 路径（后端已有 dispatch 与
  `drawIndexedIndirect`，但应用层入口与持久 GPU buffer 尚未接线）。独立 Vulkan 原型
  已经完成 cut 选择、GPU index/draw 压缩和三 pass GPU 顶点压缩；剩余工作是把它变成
  Engine 的公共对象生命周期。
- 把 mmgpu 的 Vulkan visibility buffer 接进 Filament 正式渲染器；当前是独立原型。
- 移动端真机 HTTP/HTTPS 与网络切换验证（CivetWeb 已提供便携 HTTP Range 传输，
  HTTPS 依赖平台 TLS 运行时）。
- 移动端真机功耗、带宽与帧时验证。

### 10.4 M5 移动端落地的前置条件（本轮评估）

截至本轮，代码侧的移动端相关能力已经有可验证的部分：GLSL ES 3.10 的 cut shader、
跨平台的 CivetWeb HTTP Range、Vulkan 后端的 compute/indirect 入口，以及无 Vulkan 时的
OpenGL ES 兼容路径。但 M5 的验收项**无法在本机完成**：

| 验收项 | 本机状态 | 缺少什么 |
|-|-|-|
| Android 构建 | 未配置 | `ANDROID_HOME` / `ANDROID_SDK_ROOT` 为空，无 `adb` / `sdkmanager` / NDK |
| 真机帧时、功耗、发热 | 未测 | 一台 arm64-v8a 真机 + 稳定供电与温度采集 |
| 真机 HTTP/HTTPS、网络切换 | 未测 | 真机网络与可控制的服务端 |

因此论文中不能把 M5 写成“移动端实测”。当前能站住的表述是：**桌面 Iris Xe 核显作为
移动 GPU 的代理**，并明确说明它不能代表手机的功耗/发热。若要继续 M5，最小闭环是：
安装 Android command-line tools、platform-tools 与 NDK，连接一台支持 Vulkan 1.0 或
GLES 3.1 的 arm64 设备，把 `mm_bench` 的 headless 路径移植成移动端 harness，再补齐
Perfetto/电池数据。这一步需要外部硬件，不是代码侧能独立完成的。

---
## 11. 参考

- Google Filament — https://github.com/google/filament
- 上游构建文档：`BUILDING.md`
- 仓库内 AI 开发规范：`AGENTS.md`、`skills/`
