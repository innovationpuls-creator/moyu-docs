#!/usr/bin/env node
/**
 * Generate the TypeScript projection of /contracts (doc 27 §17/§53, doc 28 §42/§44).
 *
 * Input is the registry-derived staging tree produced by
 * `scripts/generate_contracts.py` — one normalised JSON Schema per registered
 * contract, at its canonical relative path. Every registered kind
 * (Command / Query / Event / Error / Identity) is projected, including contracts
 * that carry no HTTP route.
 *
 * Never hand-edit the output; rerun `just contract` instead.
 *
 * Usage: node scripts/generate_ts_contracts.mjs <stagingDir> <outDir>
 */

import { mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { compileFromFile } from "json-schema-to-typescript";

const [, , stagingDir, outDir] = process.argv;

if (!stagingDir || !outDir) {
	console.error("usage: generate_ts_contracts.mjs <stagingDir> <outDir>");
	process.exit(2);
}

/** Deterministic walk: sorted, deepest-last, relative POSIX paths. */
async function walk(dir, prefix = "") {
	const entries = await readdir(dir, { withFileTypes: true });
	const files = [];
	for (const entry of entries.sort((a, b) => (a.name < b.name ? -1 : 1))) {
		const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
		if (entry.isDirectory()) {
			files.push(...(await walk(path.join(dir, entry.name), rel)));
		} else if (entry.name.endsWith(".json")) {
			files.push(rel);
		}
	}
	return files;
}

const schemaFiles = await walk(stagingDir);
if (schemaFiles.length === 0) {
	console.error(`no staged schema found under ${stagingDir}`);
	process.exit(1);
}

await mkdir(outDir, { recursive: true });

for (const rel of schemaFiles) {
	const source = path.join(stagingDir, rel);
	const types = await compileFromFile(source, {
		// Do NOT set `cwd`: json-schema-to-typescript defaults it to the source
		// file's directory, which is what makes relative `$ref`s resolve. Passing
		// the staging root here resolves every ref against that root instead and
		// fails with ENOENT.
		additionalProperties: false,
		// Fixed banner: the default one embeds no timestamp, but pinning it keeps
		// the artifact independent of library defaults.
		bannerComment:
			"/* eslint-disable */\n/**\n * Generated from /contracts by scripts/generate_ts_contracts.mjs.\n * Do not edit; run `just contract` instead.\n */\n",
		style: { singleQuote: false, semi: true, tabWidth: 2 },
	});
	const target = path.join(outDir, rel.replace(/\.json$/, ".d.ts"));
	await mkdir(path.dirname(target), { recursive: true });
	await writeFile(target, types, "utf8");
}

console.log(
	`generated ${schemaFiles.length} TypeScript contract module(s) into ${outDir}`,
);
