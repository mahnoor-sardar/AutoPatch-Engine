#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const lockPath = path.join(__dirname, "..", "package-lock.json");
const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
const pkg = lock.packages?.["node_modules/next"];
if (!pkg || !pkg.version) {
  console.error("F08: node_modules/next is missing from package-lock.json");
  process.exit(1);
}

const version = pkg.version;

function parse(v) {
  const parts = String(v).split(".").map((n) => Number.parseInt(n, 10));
  if (parts.length < 3 || parts.some((n) => Number.isNaN(n))) {
    throw new Error(`unparseable version: ${v}`);
  }
  return parts;
}

function cmp(a, b) {
  const left = parse(a);
  const right = parse(b);
  for (let i = 0; i < 3; i += 1) {
    if (left[i] > right[i]) return 1;
    if (left[i] < right[i]) return -1;
  }
  return 0;
}

function inRange(v, start, endExclusive) {
  return cmp(v, start) >= 0 && cmp(v, endExclusive) < 0;
}

// GHSA-c4j6-fc7j-m34r / CVE-2026-44578
const affected =
  inRange(version, "13.4.13", "15.5.16") ||
  inRange(version, "16.0.0", "16.2.5");

if (affected) {
  console.error(
    `F08: locked next@${version} is in the SSRF-affected range ` +
      `(>=13.4.13 <15.5.16 or >=16.0.0 <16.2.5)`
  );
  process.exit(1);
}

console.log(`F08: locked next@${version} is outside the affected SSRF range`);
