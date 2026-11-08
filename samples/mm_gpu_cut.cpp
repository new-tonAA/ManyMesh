#include "mm_gpu_cut.h"

#include <details/Engine.h>

#include <backend/BufferDescriptor.h>
#include <backend/DriverEnums.h>
#include <backend/Program.h>
#include <private/backend/DriverApi.h>

#include <utils/FixedCapacityVector.h>

#include <GlslangToSpv.h>
#include <glslang/Public/ShaderLang.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <mutex>
#include <utility>

namespace mmbench {

namespace {

using namespace filament;
using namespace filament::backend;
using namespace filament::manymesh;

using GpuCutParams = GpuLodCutParams;
using GpuCutCounters = GpuLodCutCounters;

const TBuiltInResource kGpuCutResourceLimits = {
    /* .MaxLights = */ 32,
    /* .MaxClipPlanes = */ 6,
    /* .MaxTextureUnits = */ 32,
    /* .MaxTextureCoords = */ 32,
    /* .MaxVertexAttribs = */ 64,
    /* .MaxVertexUniformComponents = */ 4096,
    /* .MaxVaryingFloats = */ 64,
    /* .MaxVertexTextureImageUnits = */ 32,
    /* .MaxCombinedTextureImageUnits = */ 80,
    /* .MaxTextureImageUnits = */ 32,
    /* .MaxFragmentUniformComponents = */ 4096,
    /* .MaxDrawBuffers = */ 32,
    /* .MaxVertexUniformVectors = */ 128,
    /* .MaxVaryingVectors = */ 8,
    /* .MaxFragmentUniformVectors = */ 16,
    /* .MaxVertexOutputVectors = */ 16,
    /* .MaxFragmentInputVectors = */ 15,
    /* .MinProgramTexelOffset = */ -8,
    /* .MaxProgramTexelOffset = */ 7,
    /* .MaxClipDistances = */ 8,
    /* .MaxComputeWorkGroupCountX = */ 65535,
    /* .MaxComputeWorkGroupCountY = */ 65535,
    /* .MaxComputeWorkGroupCountZ = */ 65535,
    /* .MaxComputeWorkGroupSizeX = */ 1024,
    /* .MaxComputeWorkGroupSizeY = */ 1024,
    /* .MaxComputeWorkGroupSizeZ = */ 64,
    /* .MaxComputeUniformComponents = */ 1024,
    /* .MaxComputeTextureImageUnits = */ 16,
    /* .MaxComputeImageUniforms = */ 8,
    /* .MaxComputeAtomicCounters = */ 8,
    /* .MaxComputeAtomicCounterBuffers = */ 1,
    /* .MaxVaryingComponents = */ 60,
    /* .MaxVertexOutputComponents = */ 64,
    /* .MaxGeometryInputComponents = */ 64,
    /* .MaxGeometryOutputComponents = */ 128,
    /* .MaxFragmentInputComponents = */ 128,
    /* .MaxImageUnits = */ 8,
    /* .MaxCombinedImageUnitsAndFragmentOutputs = */ 8,
    /* .MaxCombinedShaderOutputResources = */ 8,
    /* .MaxImageSamples = */ 0,
    /* .MaxVertexImageUniforms = */ 0,
    /* .MaxTessControlImageUniforms = */ 0,
    /* .MaxTessEvaluationImageUniforms = */ 0,
    /* .MaxGeometryImageUniforms = */ 0,
    /* .MaxFragmentImageUniforms = */ 8,
    /* .MaxCombinedImageUniforms = */ 8,
    /* .MaxGeometryTextureImageUnits = */ 16,
    /* .MaxGeometryOutputVertices = */ 256,
    /* .MaxGeometryTotalOutputComponents = */ 1024,
    /* .MaxGeometryUniformComponents = */ 1024,
    /* .MaxGeometryVaryingComponents = */ 64,
    /* .MaxTessControlInputComponents = */ 128,
    /* .MaxTessControlOutputComponents = */ 128,
    /* .MaxTessControlTextureImageUnits = */ 16,
    /* .MaxTessControlUniformComponents = */ 1024,
    /* .MaxTessControlTotalOutputComponents = */ 4096,
    /* .MaxTessEvaluationInputComponents = */ 128,
    /* .MaxTessEvaluationOutputComponents = */ 128,
    /* .MaxTessEvaluationTextureImageUnits = */ 16,
    /* .MaxTessEvaluationUniformComponents = */ 1024,
    /* .MaxTessPatchComponents = */ 120,
    /* .MaxPatchVertices = */ 32,
    /* .MaxTessGenLevel = */ 64,
    /* .MaxViewports = */ 16,
    /* .MaxVertexAtomicCounters = */ 0,
    /* .MaxTessControlAtomicCounters = */ 0,
    /* .MaxTessEvaluationAtomicCounters = */ 0,
    /* .MaxGeometryAtomicCounters = */ 0,
    /* .MaxFragmentAtomicCounters = */ 8,
    /* .MaxCombinedAtomicCounters = */ 8,
    /* .MaxAtomicCounterBindings = */ 1,
    /* .MaxVertexAtomicCounterBuffers = */ 0,
    /* .MaxTessControlAtomicCounterBuffers = */ 0,
    /* .MaxTessEvaluationAtomicCounterBuffers = */ 0,
    /* .MaxGeometryAtomicCounterBuffers = */ 0,
    /* .MaxFragmentAtomicCounterBuffers = */ 1,
    /* .MaxCombinedAtomicCounterBuffers = */ 1,
    /* .MaxAtomicCounterBufferSize = */ 16384,
    /* .MaxTransformFeedbackBuffers = */ 4,
    /* .MaxTransformFeedbackInterleavedComponents = */ 64,
    /* .MaxCullDistances = */ 8,
    /* .MaxCombinedClipAndCullDistances = */ 8,
    /* .MaxSamples = */ 4,
    /* .maxMeshOutputVerticesNV = */ 256,
    /* .maxMeshOutputPrimitivesNV = */ 512,
    /* .maxMeshWorkGroupSizeX_NV = */ 32,
    /* .maxMeshWorkGroupSizeY_NV = */ 1,
    /* .maxMeshWorkGroupSizeZ_NV = */ 1,
    /* .maxTaskWorkGroupSizeX_NV = */ 32,
    /* .maxTaskWorkGroupSizeY_NV = */ 1,
    /* .maxTaskWorkGroupSizeZ_NV = */ 1,
    /* .maxMeshViewCountNV = */ 4,
    /* .max_mesh_output_vertices_ext = */ 256,
    /* .max_mesh_output_primitives_ext = */ 256,
    /* .max_mesh_work_group_size_x_ext = */ 128,
    /* .max_mesh_work_group_size_y_ext = */ 128,
    /* .max_mesh_work_group_size_z_ext = */ 128,
    /* .max_task_work_group_size_x_ext = */ 128,
    /* .max_task_work_group_size_y_ext = */ 128,
    /* .max_task_work_group_size_z_ext = */ 128,
    /* .max_mesh_view_count_ext = */ 4,
    /* .maxDualSourceDrawBuffersEXT = */ 1,
    /* .limits = */
    {
        /* .nonInductiveForLoops = */ 1,
        /* .whileLoops = */ 1,
        /* .doWhileLoops = */ 1,
        /* .generalUniformIndexing = */ 1,
        /* .generalAttributeMatrixVectorIndexing = */ 1,
        /* .generalVaryingIndexing = */ 1,
        /* .generalSamplerIndexing = */ 1,
        /* .generalVariableIndexing = */ 1,
        /* .generalConstantMatrixVectorIndexing = */ 1,
    }
};

static_assert(sizeof(GpuCutCounters) == 12, "GPU cut counter layout must match the shader");

// The GPU cut traversal is shared with the backend regression in libs/manymesh.

struct CompiledShader {
    ShaderLanguage language = ShaderLanguage::ESSL3;
    std::string text;
    std::vector<uint8_t> binary;
};

std::vector<uint8_t> compileToSpirv(std::string const& source, std::string* error) {
    static std::once_flag initialize;
    std::call_once(initialize, [] { glslang::InitializeProcess(); });

    glslang::TShader shader(EShLangCompute);
    char const* sourcePointer = source.c_str();
    shader.setStrings(&sourcePointer, 1);
    shader.setAutoMapBindings(true);

    EShMessages const messages = static_cast<EShMessages>(EShMsgVulkanRules | EShMsgSpvRules);
    if (!shader.parse(&kGpuCutResourceLimits, 450, false, messages)) {
        if (error != nullptr) {
            *error = shader.getInfoLog();
        }
        return {};
    }

    glslang::TProgram program;
    program.addShader(&shader);
    if (!program.link(messages)) {
        if (error != nullptr) {
            *error = program.getInfoLog();
        }
        return {};
    }

    std::vector<unsigned int> words;
    glslang::GlslangToSpv(*program.getIntermediate(EShLangCompute), words);
    std::vector<uint8_t> bytes(words.size() * sizeof(unsigned int));
    if (!bytes.empty()) {
        std::memcpy(bytes.data(), words.data(), bytes.size());
    }
    return bytes;
}

void setError(std::string* error, char const* message) {
    if (error != nullptr) {
        *error = message;
    }
}

} // namespace

struct GpuLodCut::Impl {
    Engine* engine = nullptr;
    DriverApi* driver = nullptr;
    ShaderLanguage shaderLanguage = ShaderLanguage::ESSL3;
    std::string shaderText;
    std::vector<uint8_t> shaderBinary;
    ProgramHandle program{};
    DescriptorSetLayoutHandle descriptorSetLayout{};
    DescriptorSetHandle descriptorSet{};
    BufferObjectHandle nodeBuffer{};
    BufferObjectHandle selectionBuffer{};
    BufferObjectHandle counterBuffer{};
    BufferObjectHandle paramsBuffer{};
    uint32_t nodeCount = 0;
    bool valid = false;
};

GpuLodCut::GpuLodCut() = default;

GpuLodCut::~GpuLodCut() = default;

bool GpuLodCut::valid() const noexcept { return mImpl != nullptr && mImpl->valid; }

bool GpuLodCut::create(Engine& engine, Engine::Backend backend, GpuLodBuffer const& buffer,
        std::string* error) {
    destroy(engine);
    mImpl = std::make_unique<Impl>();
    mImpl->engine = &engine;
    mImpl->driver = &downcast(engine).getDriverApi();

    if (buffer.nodes.empty()) {
        setError(error, "GPU cut needs at least one DAG node");
        return false;
    }
    if (buffer.nodes.size() > UINT32_MAX) {
        setError(error, "GPU cut node count exceeds 32 bits");
        return false;
    }
    for (GpuLodNode const& node: buffer.nodes) {
        if (node.level >= 64) {
            setError(error, "GPU cut parent-chain walk is limited to 64 levels");
            return false;
        }
    }

    bool const mobile = engine.getDriver()->getShaderModel() == ShaderModel::MOBILE;
    if (backend == Engine::Backend::VULKAN) {
        mImpl->shaderBinary = compileToSpirv(gpuLodCutShaderSource(false), error);
        if (mImpl->shaderBinary.empty()) {
            return false;
        }
        mImpl->shaderLanguage = ShaderLanguage::SPIRV;
    } else if (backend == Engine::Backend::OPENGL) {
        mImpl->shaderText = gpuLodCutShaderSource(mobile);
        mImpl->shaderLanguage = ShaderLanguage::ESSL3;
    } else {
        setError(error, "GPU cut is implemented for Vulkan and OpenGL backends");
        return false;
    }

    mImpl->nodeCount = uint32_t(buffer.nodes.size());
    size_t const nodeBytes = buffer.nodes.size() * sizeof(GpuLodNode);
    size_t const selectionBytes = buffer.nodes.size() * sizeof(uint32_t);

    auto& driver = *mImpl->driver;
    mImpl->nodeBuffer = driver.createBufferObject(nodeBytes, BufferObjectBinding::SHADER_STORAGE,
            BufferUsage::STATIC);
    mImpl->selectionBuffer = driver.createBufferObject(selectionBytes,
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    mImpl->counterBuffer = driver.createBufferObject(sizeof(GpuCutCounters),
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::DYNAMIC);
    mImpl->paramsBuffer = driver.createBufferObject(sizeof(GpuCutParams),
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::DYNAMIC);
    driver.updateBufferObject(mImpl->nodeBuffer, { buffer.nodes.data(), nodeBytes }, 0);

    Program program;
    program.shaderLanguage(mImpl->shaderLanguage);
    if (!mImpl->shaderBinary.empty()) {
        program.shader(ShaderStage::COMPUTE, mImpl->shaderBinary.data(),
                mImpl->shaderBinary.size());
    } else {
        program.shader(ShaderStage::COMPUTE, mImpl->shaderText.data(),
                mImpl->shaderText.size() + 1);
    }
    Program::DescriptorBindingsInfo bindings(4);
    bindings[0] = { "nodeData", DescriptorType::SHADER_STORAGE_BUFFER, 0 };
    bindings[1] = { "selectionOutput", DescriptorType::SHADER_STORAGE_BUFFER, 1 };
    bindings[2] = { "counters", DescriptorType::SHADER_STORAGE_BUFFER, 2 };
    bindings[3] = { "params", DescriptorType::SHADER_STORAGE_BUFFER, 3 };
    program.descriptorBindings(0, std::move(bindings));
    mImpl->program = driver.createProgram(std::move(program));

    utils::FixedCapacityVector<DescriptorSetLayoutDescriptor> descriptors(4);
    for (uint32_t binding = 0; binding < 4; ++binding) {
        descriptors[binding] = {
            .type = DescriptorType::SHADER_STORAGE_BUFFER,
            .stageFlags = ShaderStageFlags::COMPUTE,
            .binding = descriptor_binding_t(binding),
        };
    }
    mImpl->descriptorSetLayout = driver.createDescriptorSetLayout(
            backend::DescriptorSetLayout{ .descriptors = std::move(descriptors) });
    mImpl->descriptorSet = driver.createDescriptorSet(mImpl->descriptorSetLayout);
    driver.updateDescriptorSetBuffer(mImpl->descriptorSet, 0, mImpl->nodeBuffer, 0, nodeBytes);
    driver.updateDescriptorSetBuffer(mImpl->descriptorSet, 1, mImpl->selectionBuffer, 0,
            selectionBytes);
    driver.updateDescriptorSetBuffer(mImpl->descriptorSet, 2, mImpl->counterBuffer, 0,
            sizeof(GpuCutCounters));
    driver.updateDescriptorSetBuffer(mImpl->descriptorSet, 3, mImpl->paramsBuffer, 0,
            sizeof(GpuCutParams));
    mImpl->valid = true;
    return true;
}

bool GpuLodCut::select(Engine& engine, ViewCamera const& camera, float thresholdPx,
        GpuCutResult* result, std::string* error) {
    if (!valid() || mImpl->driver == nullptr) {
        setError(error, "GPU cut resources are not initialized");
        return false;
    }
    if (result == nullptr) {
        setError(error, "GPU cut result must not be null");
        return false;
    }

    auto const start = std::chrono::steady_clock::now();
    GpuCutParams params = makeGpuLodCutParams(camera, mImpl->nodeCount, thresholdPx);

    GpuCutCounters zeroCounters{};
    auto& driver = *mImpl->driver;
    driver.updateBufferObject(mImpl->paramsBuffer, { &params, sizeof(params) }, 0);
    driver.updateBufferObject(mImpl->counterBuffer, { &zeroCounters, sizeof(zeroCounters) }, 0);
    driver.bindDescriptorSet(mImpl->descriptorSet, 0, {});
    driver.dispatchCompute(mImpl->program, { (mImpl->nodeCount + 63u) / 64u, 1, 1 });

    GpuCutCounters counters{};
    std::vector<uint32_t> selected(mImpl->nodeCount);
    driver.readBufferSubData(mImpl->counterBuffer, 0, sizeof(counters),
            { &counters, sizeof(counters) });
    driver.readBufferSubData(mImpl->selectionBuffer, 0, selected.size() * sizeof(uint32_t),
            { selected.data(), selected.size() * sizeof(uint32_t) });
    downcast(engine).flushAndWait();

    auto const end = std::chrono::steady_clock::now();
    result->wallMs = std::chrono::duration<double, std::milli>(end - start).count();
    if (counters.selectedCount > mImpl->nodeCount) {
        setError(error, "GPU cut wrote more nodes than the selection buffer can hold");
        return false;
    }

    result->nodes.assign(selected.begin(), selected.begin() + counters.selectedCount);
    result->selectedTriangles = counters.selectedTriangles;
    result->culledTriangles = counters.culledTriangles;
    return true;
}

void GpuLodCut::destroy(Engine& engine) {
    if (mImpl == nullptr) {
        return;
    }
    if (mImpl->driver != nullptr) {
        auto& driver = *mImpl->driver;
        driver.destroyDescriptorSet(mImpl->descriptorSet);
        driver.destroyDescriptorSetLayout(mImpl->descriptorSetLayout);
        driver.destroyProgram(mImpl->program);
        driver.destroyBufferObject(mImpl->paramsBuffer);
        driver.destroyBufferObject(mImpl->counterBuffer);
        driver.destroyBufferObject(mImpl->selectionBuffer);
        driver.destroyBufferObject(mImpl->nodeBuffer);
        downcast(engine).flush();
    }
    mImpl.reset();
}

} // namespace mmbench
