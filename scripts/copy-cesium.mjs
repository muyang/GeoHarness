#!/usr/bin/env node
/** 把 Cesium 的运行时静态资源拷到 public/cesium/。
 *
 *  Cesium 在运行时通过 window.CESIUM_BASE_URL 拉 Workers / Assets / Widgets / ThirdParty，
 *  这些不是 ES 模块、Vite 不会打包它们，必须原样放到静态目录。
 *  由 npm 的 predev / prebuild 钩子自动执行（见 package.json）。 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const from = path.join(root, 'node_modules', 'cesium', 'Build', 'Cesium');
const to = path.join(root, 'public', 'cesium');
const DIRS = ['Workers', 'Assets', 'Widgets', 'ThirdParty'];

if (!fs.existsSync(from)) {
  console.error(`  ✗ 找不到 ${from} —— 先执行 npm install（需要 cesium 依赖）`);
  process.exit(1);
}
// 已经同步过就跳过（按版本打标记，避免每次构建重复拷 7MB）
const version = JSON.parse(fs.readFileSync(path.join(root, 'node_modules/cesium/package.json'), 'utf8')).version;
const stamp = path.join(to, '.version');
if (fs.existsSync(stamp) && fs.readFileSync(stamp, 'utf8').trim() === version) {
  console.log(`  Cesium 资源已是最新（${version}），跳过`);
  process.exit(0);
}
fs.rmSync(to, { recursive: true, force: true });
fs.mkdirSync(to, { recursive: true });
for (const d of DIRS) {
  fs.cpSync(path.join(from, d), path.join(to, d), { recursive: true });
}
fs.writeFileSync(stamp, `${version}\n`);
console.log(`  ✅ Cesium ${version} 资源已同步到 public/cesium/`);
