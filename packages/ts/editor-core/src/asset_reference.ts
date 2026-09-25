export type AssetReferenceKind = "image" | "attachment";

export interface ParsedAssetReference {
	kind: AssetReferenceKind;
	assetId: string;
	label: string;
}

function encodeTokenPart(value: string, readableSpaces: boolean): string {
	const encoded = encodeURIComponent(value).replace(
		/[!'()*]/gu,
		(character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
	);
	return readableSpaces ? encoded.replaceAll("%20", " ") : encoded;
}

function decodeTokenPart(value: string): string {
	try {
		return decodeURIComponent(value);
	} catch {
		return value;
	}
}

/** Stable, human-readable source projection for one asset block. */
export function assetReferenceToken(
	kind: AssetReferenceKind,
	assetId: string,
	label: string,
): string {
	const encodedLabel = encodeTokenPart(label, true);
	const encodedAssetId = encodeTokenPart(assetId, false);
	return kind === "image"
		? `![${encodedLabel}](asset://${encodedAssetId})`
		: `[${encodedLabel}](asset://${encodedAssetId})`;
}

export function parseAssetReferenceToken(
	line: string,
): ParsedAssetReference | null {
	const image = line.match(/^!\[([^\]]*)\]\(asset:\/\/([^)]+)\)$/u);
	const attachment = line.match(/^\[([^\]]*)\]\(asset:\/\/([^)]+)\)$/u);
	const match = image ?? attachment;
	if (!match) return null;
	return {
		kind: image ? "image" : "attachment",
		assetId: decodeTokenPart(match[2]),
		label: decodeTokenPart(match[1]),
	};
}
