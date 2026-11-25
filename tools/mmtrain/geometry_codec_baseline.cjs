"use strict";

const fs = require("node:fs");
const { createHash } = require("node:crypto");
const { performance } = require("node:perf_hooks");
const { MeshoptEncoder, MeshoptDecoder } = require("../../third_party/meshoptimizer/js");
const draco = require("../../third_party/draco/javascript/npm/draco3d");

// The experiment's meshopt payload includes a 32-byte header and both coded streams.
function encodeMeshopt(positions, faces, origin, range, bits) {
    const indices = new Uint32Array(faces);
    const [remap, count] = MeshoptEncoder.reorderMesh(indices, true, true);
    const stride = bits <= 8 ? 4 : bits <= 16 ? 8 : 12;
    const vertices = new Uint8Array(count * stride);
    const view = new DataView(vertices.buffer);
    const inverseStep = Math.fround(((1 << bits) - 1) / range);
    const indexSize = count <= 65536 ? 2 : 4;
    for (let i = 0; i < remap.length; i++) {
        for (let axis = 0; axis < 3; axis++) {
            // Use the same float32 arithmetic as Draco's position quantizer.
            const offset = Math.fround(positions[3 * i + axis] - origin[axis]);
            const q = Math.floor(Math.fround(Math.fround(offset * inverseStep) + 0.5));
            if (stride === 4) view.setUint8(remap[i] * stride + axis, q);
            else if (stride === 8) view.setUint16(remap[i] * stride + 2 * axis, q, true);
            else view.setUint32(remap[i] * stride + 4 * axis, q, true);
        }
    }
    const packedIndices = indexSize === 2 ? Uint16Array.from(indices) : indices;
    const vertexStream = MeshoptEncoder.encodeVertexBuffer(vertices, count, stride);
    const indexStream = MeshoptEncoder.encodeIndexBuffer(
        new Uint8Array(packedIndices.buffer), indices.length, indexSize);
    const header = Buffer.alloc(32);
    origin.forEach((value, axis) => header.writeFloatLE(value, axis * 4));
    header.writeFloatLE(range, 12);
    header.writeUInt32LE(count, 16);
    header.writeUInt32LE(indices.length, 20);
    header.writeUInt32LE(vertexStream.length, 24);
    header.writeUInt8(bits, 28);
    return Buffer.concat([header, vertexStream, indexStream]);
}

function decodeMeshopt(bytes) {
    const range = bytes.readFloatLE(12);
    const count = bytes.readUInt32LE(16);
    const indexCount = bytes.readUInt32LE(20);
    const indexOffset = 32 + bytes.readUInt32LE(24);
    const bits = bytes.readUInt8(28);
    const stride = bits <= 8 ? 4 : bits <= 16 ? 8 : 12;
    const indexSize = count <= 65536 ? 2 : 4;
    const vertices = new Uint8Array(count * stride);
    const indices = indexSize === 2 ? new Uint16Array(indexCount) : new Uint32Array(indexCount);
    MeshoptDecoder.decodeVertexBuffer(vertices, count, stride, bytes.subarray(32, indexOffset));
    MeshoptDecoder.decodeIndexBuffer(new Uint8Array(indices.buffer), indexCount,
        indexSize, bytes.subarray(indexOffset));
    const positions = new Float32Array(3 * count);
    const origin = [0, 4, 8].map(offset => bytes.readFloatLE(offset));
    const step = Math.fround(range / ((1 << bits) - 1));
    const view = new DataView(vertices.buffer);
    for (let i = 0; i < count; i++) {
        for (let axis = 0; axis < 3; axis++) {
            let q;
            if (stride === 4) q = view.getUint8(i * stride + axis);
            else if (stride === 8) q = view.getUint16(i * stride + 2 * axis, true);
            else q = view.getUint32(i * stride + 4 * axis, true);
            positions[3 * i + axis] = origin[axis] + Math.fround(q * step);
        }
    }
    return [positions, Uint32Array.from(indices)];
}

function encodeDraco(module, positions, faces, origin, range, bits) {
    const mesh = new module.Mesh();
    const builder = new module.MeshBuilder();
    const encoder = new module.Encoder();
    const encoded = new module.DracoInt8Array();
    try {
        builder.AddFacesToMesh(mesh, faces.length / 3, faces);
        builder.AddFloatAttributeToMesh(mesh, module.POSITION, positions.length / 3, 3, positions);
        encoder.SetSpeedOptions(5, 5);
        encoder.SetEncodingMethod(module.MESH_EDGEBREAKER_ENCODING);
        encoder.SetAttributeExplicitQuantization(module.POSITION, bits, 3, origin, range);
        const length = encoder.EncodeMeshToDracoBuffer(mesh, encoded);
        if (length <= 0) throw new Error("Draco encoder rejected the mesh");
        return Buffer.from(Array.from({ length }, (_, i) => encoded.GetValue(i)));
    } finally {
        for (const object of [encoded, encoder, builder, mesh]) module.destroy(object);
    }
}

function decodeDraco(module, bytes) {
    const decoder = new module.Decoder();
    const mesh = new module.Mesh();
    const buffer = new module.DecoderBuffer();
    let positionPointer = 0;
    let facePointer = 0;
    try {
        buffer.Init(bytes, bytes.length);
        const status = decoder.DecodeBufferToMesh(buffer, mesh);
        if (!status.ok()) throw new Error(status.error_msg());
        const positionCount = mesh.num_points() * 3;
        const indexCount = mesh.num_faces() * 3;
        const attr = decoder.GetAttribute(mesh, decoder.GetAttributeId(mesh, module.POSITION));
        positionPointer = module._malloc(positionCount * 4);
        facePointer = module._malloc(indexCount * 4);
        if (!positionPointer || !facePointer ||
                !decoder.GetAttributeDataArrayForAllPoints(
                    mesh, attr, module.DT_FLOAT32, positionCount * 4, positionPointer) ||
                !decoder.GetTrianglesUInt32Array(mesh, indexCount * 4, facePointer)) {
            throw new Error("Draco output extraction failed");
        }
        return [
            module.HEAPF32.slice(positionPointer / 4, positionPointer / 4 + positionCount),
            module.HEAPU32.slice(facePointer / 4, facePointer / 4 + indexCount),
        ];
    } finally {
        module._free(facePointer);
        module._free(positionPointer);
        for (const object of [buffer, mesh, decoder]) module.destroy(object);
    }
}

async function main() {
    if (process.argv.length !== 4) throw new Error("usage: node geometry_codec_baseline.cjs input.json output.json");
    const [encoder, decoder] = await Promise.all([
        draco.createEncoderModule({}), draco.createDecoderModule({}),
        MeshoptEncoder.ready, MeshoptDecoder.ready,
    ]);
    const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
    const positions = Float32Array.from(input.positions.flat());
    const faces = Uint32Array.from(input.triangles.flat());
    const origin = new Float32Array([Infinity, Infinity, Infinity]);
    const upper = new Float32Array([-Infinity, -Infinity, -Infinity]);
    for (let i = 0; i < positions.length; i++) {
        origin[i % 3] = Math.min(origin[i % 3], positions[i]);
        upper[i % 3] = Math.max(upper[i % 3], positions[i]);
    }
    // Draco serializes its float options through six decimal places.
    // Multiples of 1/64 are exact in both that decimal form and float32.
    for (let axis = 0; axis < 3; axis++) origin[axis] = Math.floor(origin[axis] * 64) / 64;
    const extent = Math.max(...Array.from(upper, (value, axis) => value - origin[axis]));
    const range = Math.ceil(extent * 64) / 64;
    const results = [];
    for (const bits of input.bits) {
        for (const [codec, encode, decode] of [
            ["meshopt", encodeMeshopt, decodeMeshopt],
            ["draco", encodeDraco.bind(null, encoder), decodeDraco.bind(null, decoder)],
        ]) {
            let result = { codec, bits };
            try {
                const start = performance.now();
                const bytes = encode(positions, faces, origin, range, bits);
                const encodeMs = performance.now() - start;
                const [decodedPositions, decodedFaces] = decode(bytes);
                const decodeMs = [];
                for (let rep = 0; rep < 11; rep++) {
                    const tick = performance.now();
                    decode(bytes);
                    decodeMs.push(performance.now() - tick);
                }
                result = {
                    ...result, bytes: bytes.length, encodeMs, decodeMs,
                    payloadSha256: createHash("sha256").update(bytes).digest("hex"),
                    positions: Array.from(decodedPositions), indices: Array.from(decodedFaces),
                };
            } catch (error) {
                result.error = error.message;
            }
            results.push(result);
        }
    }
    fs.writeFileSync(process.argv[3], JSON.stringify({ origin: Array.from(origin), range, results }));
}

module.exports = { encodeDraco, decodeDraco };

if (require.main === module) {
    main().catch(error => {
        console.error(error);
        process.exitCode = 1;
    });
}
