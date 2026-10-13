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
- [ ] **M1 — 基础渲染与度量基线**
  - [x] 可运行样例渲染场景（`material_sandbox`）
  - [x] 找到并接入**超多面数测试场景**（Stanford Asian Dragon，7,219,045 三角面）
  - [ ] 搭好画质度量（PSNR / SSIM / LPIPS）与性能采集（GPU time / memory / 功耗）
  - [ ] 用 Filament 渲染高模场景并采集真实 FPS / GPU time
- [x] **M2 — 几何侧：Mobile Geometry Optimization Layer**（首个切片，见 §7.1）
  - 离线 mesh cluster 化 + 每 cluster 的 error metric
  - 屏幕空间误差驱动的 cluster 选择
  - QEM / mesh simplification 生成低复杂度 mesh（全局链 + 逐 cluster 两种模式）
  - 产出 **Geometry Error Map**（离线软件光栅化原型）
  - [ ] 后续：cluster 组（cluster group）简化以追平全局链的质量
- [ ] **M3 — 图像侧：移动端轻量神经重建**
  - 低分辨率渲染 + 多 buffer 输入（color / depth / normal / motion / error map）
  - 轻量 CNN 超分与残差细节恢复
  - 端侧推理耗时与模型体量调优
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

**两种模式对比（同一模型，5 级，比例 0.7）**：

| 模式 | 最粗一级面数 | 最大世界空间误差 |
|-|-|-|
| 全局链（≈ Baseline 2 传统 LOD） | 1,733,244（24%） | **0.0169** |
| 逐 cluster（锁定边界） | 2,366,276（33%） | **0.0779** |

> **关键发现（决定 M2 后续方向）：** 逐 cluster 独立简化**多用了 36% 的三角形**，
> 误差却是全局链的 **4.6 倍**。根因是独立简化时边界被锁死，每个 cluster 只能在自己
> 的一小片区域里做 QEM，误差无法跨 cluster 重新分配。Nanite 采用 **cluster group**
> （成组简化、组内共享边界）正是为了绕开这一点。因此 M2 的下一步是把简化单元从
> 「单个 cluster」提升到「cluster 组」，同时**保留逐 cluster 的屏幕空间选择粒度**。

> **另一个观察：** 对这个过采样严重的扫描模型，屏幕空间误差几乎不构成约束——即使
> 最粗一级，最大误差也只有约 0.46 px（预算 1.0 px），把预算收紧 4 倍到 0.25 px 后
> 选择结果几乎不变。这恰好印证了 ManyMesh 的前提：**扫描模型的面数远超声学需要，
> 可以大幅压缩而保持亚像素精度**，真正的瓶颈在几何处理开销而非视觉质量。

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
