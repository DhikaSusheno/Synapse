// lib/platformSettings.test.ts
// Test untuk helper compose path hasil browse (BUG-43).

import { test } from "node:test";
import assert from "node:assert/strict";

import { joinBrowsePath } from "./platformSettings.ts";

test("joinBrowsePath: path Windows memakai backslash", () => {
  assert.equal(joinBrowsePath("C:\\Users\\dhika", "proyek"), "C:\\Users\\dhika\\proyek");
  // Separator yang ditambahkan untuk drive letter selalu backslash. Base yang
  // diketik user pakai forward slash tetap apa adanya - Windows dan backend
  // menerima campuran itu, dan menormalkan seluruh path di sini hanya
  // menambah tempat salah.
  assert.equal(joinBrowsePath("C:/Users/dhika", "proyek"), "C:/Users/dhika\\proyek");
});

test("joinBrowsePath: path POSIX memakai slash", () => {
  assert.equal(joinBrowsePath("/home/dhika", "proyek"), "/home/dhika/proyek");
  assert.equal(joinBrowsePath("/home/dhika/", "proyek"), "/home/dhika/proyek");
});

test("joinBrowsePath: slash ganda di ujung tidak jadi separator ganda", () => {
  assert.equal(joinBrowsePath("C:/Users/dhika//", "api"), "C:/Users/dhika\\api");
  assert.equal(joinBrowsePath("/home/dhika///", "api"), "/home/dhika/api");
  assert.equal(joinBrowsePath("C:\\Users\\dhika\\", "api"), "C:\\Users\\dhika\\api");
});

test("joinBrowsePath: base kosong mengembalikan nama apa adanya", () => {
  // Pemilih folder bisa menerima path relatif dari root drive; jangan
  // menambahkan separator di depan nama.
  assert.equal(joinBrowsePath("", "proyek"), "proyek");
  assert.equal(joinBrowsePath("/", "proyek"), "proyek");
});

test("joinBrowsePath: hasil bisa langsung dipakai browse lagi (idempoten traversal)", () => {
  // Alur nyata: pilih -> child -> child lagi. Kalau penyusunan path salah,
  // langkah kedua sudah menghasilkan path yang tidak pernah ada.
  const root = "C:\\Users\\dhika";
  const one = joinBrowsePath(root, "synapse-repo");
  const two = joinBrowsePath(one, "backend");
  const three = joinBrowsePath(two, "tests");
  assert.equal(one, "C:\\Users\\dhika\\synapse-repo");
  assert.equal(two, "C:\\Users\\dhika\\synapse-repo\\backend");
  assert.equal(three, "C:\\Users\\dhika\\synapse-repo\\backend\\tests");
  assert.ok(!one.includes("//"), "tidak boleh ada separator ganda");
  assert.ok(!one.startsWith("C:\\C:"), "drive letter tidak boleh terduplikasi");
});
