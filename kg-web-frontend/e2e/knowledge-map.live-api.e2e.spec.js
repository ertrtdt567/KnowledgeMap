import { expect, test } from "@playwright/test";

test("本地 API 可加载课程根图", async ({ page }) => {
  test.skip(!process.env.KG_E2E_LIVE, "仅在本地 API 已启动时执行");

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "五门课程知识图谱" })).toBeVisible();
  await expect(page.getByLabel("知识图谱画布").locator(".cy-canvas")).toBeVisible();
  await expect(page.getByLabel("节点层级图例")).toBeVisible();
  await expect(page.locator(".state-message.is-error")).toHaveCount(0);
});
