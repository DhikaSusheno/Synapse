// lib/fileTree.ts
// Pohon file dari daftar path datar. Dipakai dua sumber sekaligus: respons
// `git/trees?recursive=true` dari GitHub, dan hasil walking folder lokal
// lewat File System Access API. Keduanya datar, sedangkan FileTreeBrowser
// consuming pohon bersarang.
//
// Ekstraksi ini karena aturannya identik dan hairy: direktori tidak pernah ada
// di daftar, jadi harus disimpulkan dari segmen path, dan sort-nya harus
// direktori-lalu-file supaya repo besar masih terbaca.

export interface FileTreeNode {
  /** Unik di antara file dan direktori: direktori selalu berakhiran "/". */
  id: string;
  name: string;
  /** Path relatif, tanpa slash di depan. */
  path: string;
  type: "file" | "dir";
  children?: FileTreeNode[];
}

interface MutableDir {
  name: string;
  path: string;
  dirs: Map<string, MutableDir>;
  files: FileTreeNode[];
}

/**
 * Bangun pohon dari daftar path relatif. Setiap path dianggap file;
 * direktori dibuat sesuai kebutuhan.
 *
 * Segmen kosong dilewati, jadi path rusak tidak menghasilkan direktori hantu.
 * Path dengan slash di depan tetap memakai path aslinya sebagai id - data
 * seperti itu tidak terjadi di git, jadi menormalkannya hanya menambah
 * tempat untuk salah.
 */
export function buildTreeFromPaths(paths: Iterable<string>): FileTreeNode[] {
  const root: MutableDir = { name: "", path: "", dirs: new Map(), files: [] };

  // Array.from, bukan for-of langsung: target-nya es5 tanpa
  // downlevelIteration, jadi for-of hanya boleh di atas Array.
  for (const raw of Array.from(paths)) {
    const segments = raw.split("/").filter(Boolean);
    if (!segments.length) continue;

    let dir = root;
    for (const segment of segments.slice(0, -1)) {
      const path = dir.path ? `${dir.path}/${segment}` : segment;
      let next = dir.dirs.get(segment);
      if (!next) {
        next = { name: segment, path, dirs: new Map(), files: [] };
        dir.dirs.set(segment, next);
      }
      dir = next;
    }

    const name = segments[segments.length - 1];
    dir.files.push({ id: raw, name, path: raw, type: "file" });
  }

  return materialize(root);
}

function materialize(dir: MutableDir): FileTreeNode[] {
  const dirs: FileTreeNode[] = Array.from(dir.dirs.values())
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((child) => ({
      id: `${child.path}/`,
      name: child.name,
      path: child.path,
      type: "dir" as const,
      children: materialize(child),
    }));

  const files = [...dir.files].sort((a, b) => a.name.localeCompare(b.name));
  return [...dirs, ...files];
}

/** Hitung jumlah file di seluruh subtree, untuk ringkasan di header. */
export function countFiles(nodes: readonly FileTreeNode[]): number {
  let total = 0;
  for (const node of nodes) {
    if (node.type === "file") total += 1;
    else total += countFiles(node.children ?? []);
  }
  return total;
}

/** Jumlah folder di seluruh subtree. */
export function countDirs(nodes: readonly FileTreeNode[]): number {
  let total = 0;
  for (const node of nodes) {
    if (node.type === "dir") total += 1 + countDirs(node.children ?? []);
  }
  return total;
}
