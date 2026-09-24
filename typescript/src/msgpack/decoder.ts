/**
 * MessagePack decoder.
 */

import { SerdeError, SerdeErrorCode } from '../error.js';
import type { Value } from '../value.js';

/** Decode MessagePack bytes into a Value. */
export function decode(input: Uint8Array): Value {
  const decoder = new MsgPackDecoder(input);
  return decoder.decodeValue();
}

class MsgPackDecoder {
  private data: Uint8Array;
  private view: DataView;
  private pos = 0;

  constructor(data: Uint8Array) {
    this.data = data;
    this.view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  }

  decodeValue(): Value {
    const byte = this.readU8();

    // Positive fixint
    if (byte <= 0x7F) return byte;
    // Negative fixint
    if (byte >= 0xE0) return byte - 256;
    // Fixmap
    if (byte >= 0x80 && byte <= 0x8F) return this.decodeMap(byte & 0x0F);
    // Fixarray
    if (byte >= 0x90 && byte <= 0x9F) return this.decodeArray(byte & 0x0F);
    // Fixstr
    if (byte >= 0xA0 && byte <= 0xBF) return this.decodeString(byte & 0x1F);

    switch (byte) {
      case 0xC0: return null;
      case 0xC2: return false;
      case 0xC3: return true;
      // bin 8/16/32
      case 0xC4: return this.decodeBin(this.readU8());
      case 0xC5: return this.decodeBin(this.readU16());
      case 0xC6: return this.decodeBin(this.readU32());
      // ext 8/16/32
      case 0xC7: { const len = this.readU8(); this.pos++; return this.decodeBin(len); }
      case 0xC8: { const len = this.readU16(); this.pos++; return this.decodeBin(len); }
      case 0xC9: { const len = this.readU32(); this.pos++; return this.decodeBin(len); }
      // float 32/64
      case 0xCA: { const f = this.view.getFloat32(this.pos); this.pos += 4; return f; }
      case 0xCB: { const f = this.view.getFloat64(this.pos); this.pos += 8; return f; }
      // uint 8/16/32/64
      case 0xCC: return this.readU8();
      case 0xCD: return this.readU16();
      case 0xCE: return this.readU32();
      case 0xCF: {
        const hi = this.readU32();
        const lo = this.readU32();
        return hi * 0x100000000 + lo;
      }
      // int 8/16/32/64
      case 0xD0: { const v = this.readU8(); return v > 127 ? v - 256 : v; }
      case 0xD1: { const v = this.readU16(); return v > 32767 ? v - 65536 : v; }
      case 0xD2: { const v = this.readU32(); return v > 0x7FFFFFFF ? v - 0x100000000 : v; }
      case 0xD3: {
        const hi = this.readU32();
        const lo = this.readU32();
        const val = hi * 0x100000000 + lo;
        return hi > 0x7FFFFFFF ? val - 0x10000000000000000 : val;
      }
      // fixext 1/2/4/8/16
      case 0xD4: this.pos++; return this.decodeBin(1);
      case 0xD5: this.pos++; return this.decodeBin(2);
      case 0xD6: this.pos++; return this.decodeBin(4);
      case 0xD7: this.pos++; return this.decodeBin(8);
      case 0xD8: this.pos++; return this.decodeBin(16);
      // str 8/16/32
      case 0xD9: return this.decodeString(this.readU8());
      case 0xDA: return this.decodeString(this.readU16());
      case 0xDB: return this.decodeString(this.readU32());
      // array 16/32
      case 0xDC: return this.decodeArray(this.readU16());
      case 0xDD: return this.decodeArray(this.readU32());
      // map 16/32
      case 0xDE: return this.decodeMap(this.readU16());
      case 0xDF: return this.decodeMap(this.readU32());
      default:
        throw new SerdeError(SerdeErrorCode.SyntaxError, `unknown msgpack byte 0x${byte.toString(16)}`);
    }
  }

  private decodeString(len: number): string {
    const bytes = this.data.subarray(this.pos, this.pos + len);
    this.pos += len;
    return new TextDecoder().decode(bytes);
  }

  private decodeBin(len: number): Uint8Array {
    const bytes = this.data.slice(this.pos, this.pos + len);
    this.pos += len;
    return bytes;
  }

  private decodeArray(len: number): Value[] {
    const arr: Value[] = [];
    for (let i = 0; i < len; i++) arr.push(this.decodeValue());
    return arr;
  }

  private decodeMap(len: number): { [key: string]: Value } {
    const map: { [key: string]: Value } = {};
    for (let i = 0; i < len; i++) {
      const key = this.decodeValue();
      const val = this.decodeValue();
      map[String(key)] = val;
    }
    return map;
  }

  private readU8(): number {
    if (this.pos >= this.data.length) throw new SerdeError(SerdeErrorCode.UnexpectedEof, 'unexpected eof');
    return this.data[this.pos++];
  }

  private readU16(): number {
    if (this.pos + 2 > this.data.length) throw new SerdeError(SerdeErrorCode.UnexpectedEof, 'unexpected eof');
    const val = this.view.getUint16(this.pos);
    this.pos += 2;
    return val;
  }

  private readU32(): number {
    if (this.pos + 4 > this.data.length) throw new SerdeError(SerdeErrorCode.UnexpectedEof, 'unexpected eof');
    const val = this.view.getUint32(this.pos);
    this.pos += 4;
    return val;
  }
}
