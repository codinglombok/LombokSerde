/**
 * Serialize and Deserialize interfaces.
 */

import { Value } from './value.js';

/** Interface for types that can be serialized to a Value. */
export interface Serialize {
  serialize(): Value;
}

/** Interface for types that can be deserialized from a Value. */
export interface DeserializeStatic<T> {
  deserialize(value: Value): T;
}
