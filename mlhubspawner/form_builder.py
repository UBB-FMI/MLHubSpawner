import json
import os

try:
    import pkg_resources
except ImportError:
    pkg_resources = None

class JupyterFormBuilder():
    def __init__(self):
        # Read the default template for the form
        if pkg_resources is not None:
            try:
                resource_path = pkg_resources.resource_filename('mlhubspawner', 'resources/form.html')
                with open(resource_path, 'r') as file:
                    self.form_html_content = file.read()
            except Exception as e:
                self.form_html_content = f"FORM_TEMPLATE_ERROR: {e}"
        else:
            # When pkg_resources is not available, assume that the 'resources' folder
            # is in the same directory as this file.
            try:
                resource_path = os.path.join(os.path.dirname(__file__), 'resources', 'form.html')
                with open(resource_path, 'r') as file:
                    self.form_html_content = file.read()
            except Exception as e:
                self.form_html_content = f"FORM_TEMPLATE_ERROR (local): {e}"

    def _safe_fetch(self, formdata, key, default):
        return formdata[key][0] if key in formdata else default
    
    def get_html_page(self, dicitonaryList, nodeHealthSnapshots=None):
        payload = {
            "machines": dicitonaryList,
            "nodeHealth": nodeHealthSnapshots or {},
        }
        jsonPayload = json.dumps(payload).replace("</", "<\\/")
        return self.form_html_content.replace("{formPayload}", jsonPayload)

    def get_form_options(self, formdata):
        options = {}
        options['machineSelect'] = int(self._safe_fetch(formdata, 'machineSelect', 0))
        options['sharedAccess'] = bool(self._safe_fetch(formdata, 'sharedAccess', False))
        return options
