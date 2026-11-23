"use strict";

const fs = require("fs");
const path = require("path");
const simplifier = require(path.resolve(__dirname,
    "../../third_party/meshoptimizer/js/meshopt_simplifier.js"));

async function main() {
    if (process.argv.length !== 4) {
        throw new Error("usage: node meshopt_simplify.cjs input.json output.json");
    }
    await simplifier.ready;
    const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
    const positions = Float32Array.from(input.positions.flat());
    const indices = Uint32Array.from(input.triangles.flat());
    if (positions.length % 3 !== 0 || indices.length % 3 !== 0 ||
            input.targetTriangles < 1 || input.targetTriangles * 3 > indices.length) {
        throw new Error("invalid meshoptimizer input");
    }
    const [result, error] = simplifier.simplify(
        indices, positions, 3, input.targetTriangles * 3,
        input.targetError, ["LockBorder"]);
    fs.writeFileSync(process.argv[3], JSON.stringify({
        indices: Array.from(result),
        error,
        inputTriangles: indices.length / 3,
        requestedTriangles: input.targetTriangles,
        outputTriangles: result.length / 3,
        flags: ["LockBorder"],
    }));
}

main().catch((error) => {
    process.stderr.write(String(error && error.stack || error) + "\n");
    process.exitCode = 1;
});
