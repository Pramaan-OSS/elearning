"""Configure the retained local infrastructure and disable inherited
outside-sync paths that this app never uses."""
import frappe


def ignore_outside_sync(*args, **kwargs):
    """Unused inherited sync hooks must not load a vendor client."""
    return None


def install_local_boundaries():
    # These hooks run even with no configured connection. Disable the hooks,
    # rather than retaining unused SDKs just to satisfy their lazy imports.
    from importlib import import_module

    disabled = {
        "frappe.integrations.doctype.google_contacts.google_contacts": [
            "insert_contacts_to_google_contacts", "update_contacts_to_google_contacts", "sync",
        ],
        "frappe.integrations.doctype.google_calendar.google_calendar": [
            "insert_event_in_google_calendar", "update_event_in_google_calendar",
            "delete_event_from_google_calendar", "sync",
        ],
    }
    for name, functions in disabled.items():
        module = import_module(name)
        for function in functions:
            setattr(module, function, ignore_outside_sync)
