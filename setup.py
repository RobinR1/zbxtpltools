#!/usr/bin/python3

import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name='zbxtpltools',
    version='0.1.4',
    author="Robin Roevens",
    author_email="Robin.Roevens@disroot.org",
    description="Export/Import Zabbix templates to/from GIT repository",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/RobinR1/zbxtpltools",
    packages=setuptools.find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "Topic :: System :: Monitoring",
        "Topic :: Software Development :: Version Control",
        "Topic :: Utilities",
        "License :: OSI Approved :: MIT License"
        ],
    python_requires='>=3',
    install_requires=[
        'pyzabbix',
        'pygit2>0.26,<= 1.0.3'
        ],

    entry_points={
        'console_scripts': [
            'zbxtpl2git=zbxtpltools.zbxtpl2git:main',
            'zbxgit2tpl=zbxtpltools.zbxgit2tpl:main',
            ]
        },
    data_files=[
        ('etc/zbxtpltools', ['zbxtpltools/conf/zbxtpl2git.conf.example',
                             'zbxtpltools/conf/zbxgit2tpl.conf.example']),
    ],
)
