import { realpathSync } from 'node:fs';
import { spawn } from 'node:child_process';

// Windows has a case-insensitive filesystem, so the project root can be entered
// under different casings (e.g. `documents\github` vs the real `Documents\GitHub`).
// When the terminal CWD casing differs from the on-disk casing, webpack resolves
// `node_modules/next/...` under both spellings and emits "multiple modules with
// names that only differ in casing" warnings (and double-loads Next internals).
//
// `realpathSync.native` returns the OS-canonical path (correct casing), so we pin
// the CWD to it before launching Next. This makes the dev server immune to however
// the terminal or editor happened to open the folder.
process.chdir(realpathSync.native(process.cwd()));

spawn('next', ['dev', '--webpack'], { stdio: 'inherit', shell: true })
  .on('exit', (code) => process.exit(code ?? 0));
