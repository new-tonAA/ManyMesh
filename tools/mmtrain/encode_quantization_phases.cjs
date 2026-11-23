"use strict";

const fs = require("node:fs");
const { createHash } = require("node:crypto");
const { performance } = require("node:perf_hooks");
const draco = require("../../third_party/draco/javascript/npm/draco3d");
const { encodeDraco, decodeDraco } = require("./geometry_codec_baseline.cjs");

async function main() {
    if (process.argv.length !== 4) {
        throw new Error("usage: node encode_quantization_phases.cjs input.json output.json");
    }
    const [encoder, decoder] = await Promise.all([
        draco.createEncoderModule({}), draco.createDecoderModule({}),
    ]);
    const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
    const positions = Float32Array.from(input.positions.flat());
    const faces = Uint32Array.from(input.triangles.flat());
    const rows = [];
    for (const { origin, range, bits } of input.configurations) {
        const encodeStart = performance.now();
        const payload = encodeDraco(encoder, positions, faces, origin, range, bits);
        const encodeMs = performance.now() - encodeStart;
        const [vertices, indices] = decodeDraco(decoder, payload);
        const decodeMs = [];
        for (let i = 0; i < 11; i++) {
            const start = performance.now();
            decodeDraco(decoder, payload);
            decodeMs.push(performance.now() - start);
        }
        rows.push({
            bytes: payload.length, encodeMs, decodeMs,
            sha256: createHash("sha256").update(payload).digest("hex"),
            positions: Array.from(vertices), indices: Array.from(indices),
        });
    }
    fs.writeFileSync(process.argv[3], JSON.stringify(rows));
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
