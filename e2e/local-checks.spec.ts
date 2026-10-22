// Local one-command checks for this template's must-see surfaces: the main
// page, a live-class screen with a seeded class, and the checkout return
// page. Data is seeded through the app's own API with fake-safe values; no
// outside call is made. Run with PLAYWRIGHT_BASE_URL pointed at the local
// stack; screenshots land in .scratch/.
import { test, expect } from "./fixtures";
import { authFile, baseURL } from "./config";
import { csrfToken } from "./helpers";

import { request as playwrightRequest } from "@playwright/test";
import fs from "node:fs";

const SHOT_DIR = process.env.SHOT_DIR || ".scratch/qa-evidence";

async function api() {
	const context = await playwrightRequest.newContext({
		baseURL,
		storageState: authFile,
	});
	const headers = { "X-Frappe-CSRF-Token": await csrfToken(context) };
	const post = async (method: string, params: unknown) => {
		const response = await context.post(`/api/method/${method}`, {
			data: params,
			headers,
		});
		if (!response.ok()) {
			throw new Error(`${method} failed: ${response.status()} ${await response.text()}`);
		}
		return (await response.json()).message;
	};
	return { post };
}

async function screenshot(page: import("@playwright/test").Page, name: string) {
	fs.mkdirSync(SHOT_DIR, { recursive: true });
	await page.screenshot({ path: `${SHOT_DIR}/${name}.png`, fullPage: true });
}

test.describe.configure({ mode: "serial" });

let courseName = "";
let batchName = "";
let paymentName = "";

test("main page renders the learning shell", async ({ page }) => {
	await page.goto("/lms");
	await expect(page.locator("body")).toContainText(/eLearning|Courses|Log in/i, {
		ignoreCase: true,
	});
	await screenshot(page, "local-main-page");
});

test("a seeded live class is visible on the batch classes screen", async ({
	page,
}) => {
	const { post } = await api();

	// A paid-free course, a batch, and one live class row stored as the
	// platform would return it (no conferencing call is made here).
	courseName = (await post("frappe.client.insert", {
		doc: {
			doctype: "LMS Course",
			title: `Local Checks Course ${Date.now()}`,
			short_introduction: "Local check course",
			description: "Local check course",
			paid_course: 1, course_price: 500, currency: "USD",
			instructors: [{ instructor: "Administrator" }],
		},
	})).name;
	batchName = (await post("frappe.client.insert", {
		doc: {
			doctype: "LMS Batch",
			title: `Local Checks Batch ${Date.now()}`,
			description: "Local check batch", batch_details: "<p>Local check batch</p>",
			instructors: [{ instructor: "Administrator" }],
			start_date: new Date().toISOString().slice(0, 10),
			end_date: new Date(Date.now() + 26 * 864e5).toISOString().slice(0, 10),
			start_time: "09:00:00",
			end_time: "11:00:00",
			timezone: "Asia/Kolkata",
			published: 1,
			deadline: new Date(Date.now() + 20 * 864e5).toISOString().slice(0, 10),
		},
	})).name;

	await post("frappe.client.insert", {
		doc: {
			doctype: "LMS Live Class",
			title: "Local checks class",
			host: "Administrator",
			date: new Date(Date.now() + 864e5).toISOString().slice(0, 10),
			time: "10:00:00",
			duration: 60,
			timezone: "Asia/Kolkata",
			batch_name: batchName,
			conferencing_provider: "meetapp",
			join_url: "https://meet.example/j/local-checks",
			start_url: "https://meet.example/h/local-checks",
			meeting_id: "room/local-checks",
			uuid: "room/local-checks",
			// The class doc's own after_insert creates the calendar event; with
			// the site inbox unset it is left for the scheduler, which is the
			// honest local state.
		},
	});

	await page.goto(`/lms/batches/${batchName}#classes`);
	await expect(page.locator("body")).toContainText(/Live Class|Classes/i);
	await expect(page.locator("body")).toContainText("Local checks class");
	await screenshot(page, "local-live-class");
});

test("the checkout return page renders a seeded payment", async ({ page }, testInfo) => {
	testInfo.annotations.push({type: "expected-fake-refusal", description: "The fake client refuses confirmation without recording a paid enrollment."});
	const { post } = await api();

	const address = (await post("frappe.client.insert", {doc: {
		doctype: "Address", address_title: `Local Checks ${Date.now()}`, address_type: "Billing",
		address_line1: "1 Test Street", city: "London", country: "United Kingdom",
	}})).name;
	const source = (await post("frappe.client.insert", {doc: {doctype: "LMS Source", source: `Local Checks ${Date.now()}`}})).name;

	paymentName = (await post("frappe.client.insert", {
		doc: {
			doctype: "LMS Payment",
			member: "Administrator",
			billing_name: "Local Checks",
			amount: 500,
			currency: "USD", address, source, member_consent: 1,
			payment_for_document_type: "LMS Course",
			payment_for_document: courseName,
			checkout_ref: "ref/local-checks",
		},
	})).name;

	await page.goto(`/lms/billing/course/${courseName}?payment=${paymentName}`);
	await expect(page.getByTestId("checkout-return")).toBeVisible();
	await expect(page.getByRole("button", {name: "Check payment again"})).toBeVisible();
	await expect(page.getByTestId("checkout-return")).toContainText(/unavailable|not available|not confirmed/i);
	await screenshot(page, "local-checkout-return");
});
