import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const { MeshoptEncoder } = await import(pathToFileURL(process.argv[2]).href);
await MeshoptEncoder.ready;
const data = fs.readFileSync(0);
const result = [];
let offset = 0;
while (offset < data.length) {
    if (offset + 4 > data.length) {
        throw new Error('Incomplete index count');
    }
    const length = data.readUInt32LE(offset);
    offset += 4;
    if (length === 0 || length % 3 !== 0 || offset + length * 4 > data.length) {
        throw new Error('Invalid triangle index stream');
    }
    const original = new Uint32Array(length);
    Buffer.from(original.buffer).set(data.subarray(offset, offset + length * 4));
    offset += length * 4;
    for (const useCache of [false, true]) {
        const indices = original.slice();
        const [remap, vertexCount] = MeshoptEncoder.reorderMesh(indices, useCache, false);
        const header = Buffer.alloc(8);
        header.writeUInt32LE(remap.length, 0);
        header.writeUInt32LE(vertexCount, 4);
        result.push(header, Buffer.from(indices.buffer), Buffer.from(remap.buffer));
    }
}
process.stdout.write(Buffer.concat(result));
