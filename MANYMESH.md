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
  - [ ] 后续：层次化 cluster 组 / 多级 DAG，在保留细粒度选择的同时进一步逼近链的质量
- [ ] **M3 — 图像侧：移动端轻量神经重建**（首个切片，见 §7.3）
  - [x] 配对数据生成（多视角、同一相机列表、逐视角误差图）
  - [x] 轻量 CNN 重建：等分辨率下比粗几何高 **+1.88 dB**；半分辨率下比双三次高 **+0.98 dB**
  - [x] 与已发表轻量超分网络（ESPCN / FSRCNN）在同等小数据预算下对比
  - [x] 消融：**Geometry Error Map 目前没有带来有意义的收益**（−0.19 ~ +0.13 dB，符号不定）
  - [ ] 让误差图真正起作用：更激进的压缩 / 逐视角归一化 / cluster 级条件编码
  - [ ] depth / normal / motion 等其余 buffer 输入
  - [ ] 端侧推理耗时与模型体量调优；LPIPS
- [ ] **M4 — 联合优化（论文核心）**
  - 由「神经重建能力 + 预计视觉损失」反推几何预算
  - 动态策略：不同场景/运动状态采用不同压缩程度
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

> **公平性声明：** ESPCN / FSRCNN 在这里低于双三次，**不代表这些架构差**。它们的原论文
> 用数万张图像训练十万级迭代，而我这里是 12 张图、1500 次迭代——差距来自数据预算，
> 不是架构。表中的它们只能读作"在同等极小预算下"。

---

## 8. 为什么这个方案优于「移动端 Nanite」

- 不需要复刻 UE 级 Nanite
- 不依赖 NVIDIA 硬件（DLSS 不可用）
- 可以基于 Filament 落地（开源、跨平台、已有 Android 支持）
- 有明确的 baseline 对比
- 有 AI 元素
- 与「MegaLights：采样 + 重建」的研究思路一致

技术路线也符合当下实时渲染的发展方向：
**把不可承受的计算复杂度转化为可控制的近似误差，再用重建技术补偿。**

---

## 9. 开发环境与构建（当前状态）

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

## 10. 参考

- Google Filament — https://github.com/google/filament
- 上游构建文档：`BUILDING.md`
- 仓库内 AI 开发规范：`AGENTS.md`、`skills/`
