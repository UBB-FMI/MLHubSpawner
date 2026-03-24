#!/usr/bin/env python

from traitlets.config import Configurable, Config
from traitlets import List, Instance, TraitError
from .remote_hosts.remote_ml_host import RemoteMLHost
from .config_parsers import DictionaryInstanceParser
from .mlhubspawner import MLHubSpawner

if __name__ == "__main__":
    from traitlets.config import Config

    # Create a Config instance with your settings.
    config = Config()
    config.MLHubSpawner.remote_hosts = [
        {
            "codename": "Brocoli",
            "hostnames": [ "RTX 4090 - N4" , "asdf" , "asdff"],
            "port": 9000,
            "exclusive_access_enabled": False,
            "privileged_access_required": True,
            "cpu_model": "Intel Xeon",
            "cpu_cores": 16,
            "ram": 64,
            "gpu": ["NVIDIA Tesla V100", "NVIDIA Tesla P100"],
            "storage": [("SSD", 1024),("SSDE", 1024)]
        },
        { 
            "codename": "Yeah",
            "hostnames":  [ "RTX 4090 - N1" , "asdffdsa"],
            "port": 9001,
            "exclusive_access_enabled": True,
            "privileged_access_required": False,
            "cpu_model": "AMD EPYC",
            "cpu_cores": 32,
            "ram": 128,
            "gpu": ["NVIDIA Tesla A100"],
            "storage": [("NVMe", 2048),("SSD", 1024)]
        },
    ]

    
    # Instantiate the spawner with the configuration.
    spawner = MLHubSpawner(config=config)
    #spawner.user.name = "alexandru.kiraly@ubbcluj.ro"

    # Check what remote_hosts is set to:
    #print("remote_hosts:", spawner.debug())
    print("Options form:", spawner._build_options_form())
