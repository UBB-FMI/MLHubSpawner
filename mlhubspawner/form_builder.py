import json
import os

class JupyterFormBuilder():
    def __init__(self):
        try:
            resource_path = os.path.join(os.path.dirname(__file__), 'resources', 'form.html')
            with open(resource_path, 'r') as file:
                self.form_html_content = file.read()
        except Exception as e:
            self.form_html_content = f"FORM_TEMPLATE_ERROR: {e}"

    def _safe_fetch(self, formdata, key, default):
        return formdata[key][0] if key in formdata else default

    def _parse_bool(self, value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        normalized_value = str(value).strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off", ""}:
            return False
        return default
    
    def get_html_page(self, dicitonaryList, nodeHealthSnapshots=None, uiContext=None):
        payload = {
            "machines": dicitonaryList,
            "nodeHealth": nodeHealthSnapshots or {},
            "uiContext": uiContext or {},
        }
        jsonPayload = json.dumps(payload).replace("</", "<\\/")
        return self.form_html_content.replace("{formPayload}", jsonPayload)

    def get_form_options(self, formdata):
        options = {}
        options['machineSelect'] = int(self._safe_fetch(formdata, 'machineSelect', 0))
        shared_access_value = self._safe_fetch(
            formdata,
            'sharedAccessValue',
            self._safe_fetch(formdata, 'sharedAccess', True),
        )
        options['sharedAccess'] = self._parse_bool(shared_access_value, True)
        return options
