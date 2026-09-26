/**
 * `crypto.randomUUID()` is restricted to secure contexts. Browsers can still
 * reach the app over plain HTTP on a LAN IP, where `getRandomValues()` remains
 * available, so provide the same UUID v4 format for that case.
 */
const webCrypto = globalThis.crypto;

if (typeof webCrypto.randomUUID !== "function") {
	Object.defineProperty(webCrypto, "randomUUID", {
		configurable: true,
		writable: true,
		value: () => {
			const bytes = webCrypto.getRandomValues(new Uint8Array(16));
			bytes[6] = (bytes[6] & 0x0f) | 0x40;
			bytes[8] = (bytes[8] & 0x3f) | 0x80;

			const hex = Array.from(bytes, (byte) =>
				byte.toString(16).padStart(2, "0"),
			).join("");
			return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
		},
	});
}
