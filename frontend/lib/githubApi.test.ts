// lib/githubApi.test.ts
// node --test "lib/*.test.ts"
//
// buildFileTree mengubah respons datar dari git/trees?recursive=true jadi
// pohon yang bisa dirender FileTreeBrowser. Dua kegagalan yang paling mahal
// dan paling sering: direktori hilang (user cuma lihat file root) dan file
// hilang (repo tampak kosong padahal isinya ada).

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ApiError,
  buildFileTree,
  decodeBase64Utf8,
  fetchConnection,
  isNotConnected,
  type GitHubTreeItem,
} from "./githubApi.ts";

function blob(path: string): GitHubTreeItem {
  return { path, mode: "100644", type: "blob", sha: path, size: 1, url: "" };
}

test("tree kosong menghasilkan array kosong", () => {
  assert.deepEqual(buildFileTree([]), []);
});

test("file di root jadi node file", () => {
  assert.deepEqual(buildFileTree([blob("README.md")]), [
    { id: "README.md", name: "README.md", path: "README.md", type: "file" },
  ]);
});

test("direktori dibuat dari segmen path, bukan dari item bertipe tree", () => {
  // GitHub tidak mengirim entri untuk direktori. Kalau implementasi hanya
  // memetakan item bertipe "tree", semua direktori hilang.
  const tree = buildFileTree([blob("frontend/app/page.tsx"), blob("backend/main.py")]);

  assert.deepEqual(
    tree.map((n) => ({ name: n.name, type: n.type })),
    [
      { name: "backend", type: "dir" },
      { name: "frontend", type: "dir" },
    ],
  );

  const frontend = tree[1];
  assert.equal(frontend.children?.[0].name, "app");
  assert.equal(frontend.children?.[0].children?.[0].name, "page.tsx");
  assert.equal(frontend.children?.[0].children?.[0].path, "frontend/app/page.tsx");
});

test("id direktori diakhiri slash supaya tidak bentrok dengan file", () => {
  // File "a" dan direktori "a/" harus punya id berbeda, kalau tidak React
  // melihat key duplikat di tree.
  const tree = buildFileTree([blob("a"), blob("a/b.txt")]);
  assert.deepEqual(
    tree.map((n) => n.id).sort(),
    ["a", "a/"],
  );
});

test("file dan direktori dengan nama sama tidak menabrak id", () => {
  // Tidak mungkin di repo git sungguhan (file dan direktori satu nama), tapi
  // kalau tetap muncul, keduanya harus tetap bisa dibedakan - kalau id-nya
  // sama React akan collapsiblekan satu node.
  const tree = buildFileTree([blob("src"), blob("src/index.ts")]);
  assert.deepEqual(
    tree.map((n) => ({ id: n.id, type: n.type })),
    [
      { id: "src/", type: "dir" },
      { id: "src", type: "file" },
    ],
  );
  assert.equal(new Set(tree.map((n) => n.id)).size, tree.length, "id duplikat");
});

test("item bertipe tree tidak dirender sebagai file", () => {
  // Submodule / symlink ke direktori muncul sebagai "tree". Kalau ikut
  // dirender sebagai file, user klik dan dapat error "bukan file".
  const tree = buildFileTree([
    { path: "vendor/lib", mode: "160000", type: "tree", sha: "x", size: 0, url: "" },
    blob("vendor/keep.txt"),
  ]);
  assert.equal(tree[0].type, "dir");
  assert.deepEqual(
    tree[0].children?.map((c) => c.name),
    ["keep.txt"],
  );
});

test("sort: direktori dulu, lalu file, keduanya nama menaik", () => {
  const tree = buildFileTree([
    blob("zzz.txt"),
    blob("aaa.txt"),
    blob("zeta/a.txt"),
    blob("alpha/b.txt"),
  ]);
  assert.deepEqual(
    tree.map((n) => n.name),
    ["alpha", "zeta", "aaa.txt", "zzz.txt"],
  );
});

test("path dengan segmen kosong tidak bikin direktori hantu", () => {
  // Guard terhadap data rusak, bukan kondisi normal: GitHub tidak pernah
  // mengirim path dengan "/" ganda atau slash di depan.
  const tree = buildFileTree([blob(""), blob("/a"), blob("a")]);
  assert.deepEqual(
    tree.map((n) => n.name),
    ["a", "a"],
    "tidak ada segmen kosong yang jadi node tersendiri",
  );
  assert.ok(
    tree.every((n) => n.type === "file" && n.children === undefined),
    "path rusak tidak boleh memunculkan subtree",
  );
});

test("depth berapa pun di-handle", () => {
  const deep = "a/b/c/d/e/f.txt";
  const tree = buildFileTree([blob(deep)]);
  let node = tree[0];
  for (const seg of ["a", "b", "c", "d", "e"]) {
    assert.equal(node.name, seg);
    node = node.children![0];
  }
  assert.equal(node.path, deep);
});

test("decodeBase64Utf8 tidak merusak karakter non-ASCII", () => {
  // atob() polos menghasilkan mojibake untuk byte UTF-8 multi-byte.
  const original = "halo, Ä— comment ✅";
  const b64 = Buffer.from(original, "utf8").toString("base64");
  assert.equal(decodeBase64Utf8(b64), original);
  assert.notEqual(atob(b64), original, "test ini tidak berarti kalau atob ternyata benar");
});

test("decodeBase64Utf8 mengabaikan whitespace dari GitHub", () => {
  const b64 = Buffer.from("halo dunia", "utf8").toString("base64");
  const wrapped = b64.replace(/(.{4})/g, "$1\n");
  assert.equal(decodeBase64Utf8(wrapped), "halo dunia");
});

// --- Bentuk error dari proxy -------------------------------------------
//
// Backend FastAPI menulis {"detail": ...}, tapi route handler proxy Next
// menulis {"error": ..., "hint": ...} dan memetakan 401 backend jadi 502
// supaya token API yang salah tidak bisa disamarkan sebagai masalah GitHub.
// Kalau frontend cuma baca "detail" dan mencocokkan "/401/" pada teks pesan,
// seluruh error dari proxy jadi "HTTP 502" dan panel repo menampilkan galat
// mentah alih-alih menawarkan tombol "Hubungkan GitHub".

const PROXY_401 = "Token API backend ditolak";

test("isNotConnected: 401 backend berarti belum terhubung", () => {
  assert.equal(isNotConnected(new ApiError(401, "No GitHub connection")), true);
});

test("isNotConnected: 502 dari proxy (jawaban 401) tetap belum terhubung", () => {
  assert.equal(isNotConnected(new ApiError(502, PROXY_401)), true);
});

test("isNotConnected: 502 lain (backend mati) bukan masalah koneksi GitHub", () => {
  // Proxy memakai 502 juga untuk "Backend tidak dapat dijangkau" - artinya
  // bedanya, dan user butuh diberi tahu, bukan disuruh login GitHub lagi.
  assert.equal(isNotConnected(new ApiError(502, "Backend tidak dapat dijangkau")), false);
});

test("isNotConnected: error lain dan non-ApiError tidak dianggap belum terhubung", () => {
  assert.equal(isNotConnected(new ApiError(500, "boom")), false);
  assert.equal(isNotConnected(new ApiError(404, "Not Found")), false);
  assert.equal(isNotConnected(new Error("jaringan mati")), false);
  assert.equal(isNotConnected("bukan error"), false);
  assert.equal(isNotConnected(undefined), false);
});

test("api() membaca key 'error' dari proxy, bukan cuma 'detail'", async () => {
  const asli = globalThis.fetch;
  let dipanggil = false;
  globalThis.fetch = (async () => {
    dipanggil = true;
    return new Response(JSON.stringify({ error: "Cross-site request ditolak" }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  try {
    await assert.rejects(fetchConnection(), (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 403);
      assert.equal(err.message, "Cross-site request ditolak");
      return true;
    });
    assert.equal(dipanggil, true, "fetch tidak terpanggil");
  } finally {
    globalThis.fetch = asli;
  }
});

test("api() tetap membaca 'detail' dari FastAPI dan bodi non-JSON tidak melempar", async () => {
  const asli = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ detail: "No GitHub connection" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;
  try {
    await assert.rejects(fetchConnection(), (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.message, "No GitHub connection");
      assert.equal(isNotConnected(err), true);
      return true;
    });
  } finally {
    globalThis.fetch = asli;
  }

  globalThis.fetch = (async () =>
    new Response("<html>502</html>", { status: 502, headers: { "Content-Type": "text/html" } })) as typeof fetch;
  try {
    await assert.rejects(fetchConnection(), (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 502);
      assert.equal(err.message, "HTTP 502");
      return true;
    });
  } finally {
    globalThis.fetch = asli;
  }
});
