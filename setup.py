from __future__ import print_function
from setuptools import setup, find_packages

setupDescription = "MLHub Spawner: A simple SSH-like spawner which launches single-user notebooks for GPU Machine Learning."

setup_args = dict(
    name='mlhubspawner',
    packages=find_packages(),
    include_package_data=True,
    version="1.0",
    description=f"{setupDescription}",
    long_description=f"{setupDescription}",
    author="Alexandru Kiraly",
    author_email="alexandru.kiraly@ubbcluj.ro",
    url="https://www.cs.ubbcluj.ro",
    license="GPL-V3",
    platforms="Linux",
    install_requires=[
        "asyncssh",
        "cryptography>=46",
        "jupyterhub",
        "ldap3",
    ],
    keywords=['Interactive', 'Interpreter', 'Shell', 'Web'],
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Science/Research',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
    ],
)

def main():
    setup(**setup_args)

if __name__ == '__main__':
    main()
