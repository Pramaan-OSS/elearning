// Copyright (c) 2021, FOSS United and contributors
// For license information, please see license.txt

frappe.ui.form.on("LMS Settings", {
	setup: function (frm) {
		frappe.call({
			method: "lms.lms.doctype.lms_settings.lms_settings.check_payments_app",
			callback: (data) => {
				if (!data.message) {
					frm.set_df_property("payment_section", "hidden", 1);
					frm.trigger("set_no_payments_app_html");
				} else {
					frm.set_df_property("no_payments_app", "hidden", 1);
				}
			},
		});
	},

});
