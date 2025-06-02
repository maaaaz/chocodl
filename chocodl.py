#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from codecs import open
from pathlib import Path
import re
import os
import argparse
import functools
import requests
import types
import concurrent.futures
import secrets
import pprint

from lxml.etree import fromstring as fromstringxml
import pypdl
import aiohttp

# Globals
VERSION = '1.0'
CHOCO_SEARCH_REQ = 'https://community.chocolatey.org/api/v2/Packages()?$filter=(tolower(Id)%20eq%20%27{}%27)%20and%20IsLatestVersion'

# Options definition
parser = argparse.ArgumentParser(description="version: " + VERSION)
main_grp = parser.add_argument_group('Main parameters')
main_grp.add_argument('-i', '--input-file', help="Input file", required = True)
main_grp.add_argument('-s', '--do-not-download', help="Do not download anything, simply print download URLs", default = False, action='store_true')
main_grp.add_argument('-d', '--output-dir', help='Output dir (default ./chocodl/)', default=os.path.abspath(os.path.join(os.getcwd(), './chocodl/')))

dl_grp = parser.add_argument_group('Download parameters')
dl_grp.add_argument('-t', '--timeout', help='Max timeout in seconds to download a file (default: 20)', default=20, type=int)

def get_dl_url(pkg, priority='x64'):
    pkg_url = ''
    pkg_sha512 = ''

    if 'dl' in pkg.keys():
        # by default, priority to x64 version
        if ('x64' in pkg['dl']) and (priority == 'x64'):
                pkg_url = pkg['dl']['x64']['dl_url']
                pkg_sha512 = pkg['dl']['x64']['sha512']
        else:
            if ('x86' in pkg['dl']):
                pkg_url = pkg['dl']['x86']['dl_url']
                pkg_sha512 = pkg['dl']['x86']['sha512']

    return pkg_url, pkg_sha512

def download_file(pkg, options):
    download_went_well = True
    pkgname, pkg = pkg
    pkg_dir = pkg['output_dir']
    pkg_url = ''
    pkg_sha512 = ''

    if not os.path.exists(pkg_dir):
        Path(pkg_dir).mkdir(parents=True, exist_ok=True)

    pkg_url, pkg_sha512 = get_dl_url(pkg)
    if pkg_url and pkg_dir and pkg_sha512:
        dl = pypdl.Pypdl(allow_reuse=False)

        dl_result = dl.start( url = pkg_url,
                              file_path = pkg_dir,
                              block=True,
                              clear_terminal=False,
                              display=False,
                              timeout=aiohttp.ClientTimeout(sock_read=options.timeout),
                              hash_algorithms='sha512'
                            )

        if dl.completed:
            for res_url, res_fut in dl_result:
                if isinstance(res_fut, pypdl.utils.FileValidator):
                    dl_hash = res_fut.get_hash('sha512')
                    if not(res_fut.validate_hash(pkg_sha512, 'sha512')):
                        print("[!] SHA512 hash mistmatch for the package '%s'\n URL:\t\t'%s'\n Expected:\t'%s'\n Got:\t\t'%s'" % (pkgname, res_url, pkg_sha512, dl_hash))
                        print('-'*80)
                        download_went_well = False

    return download_went_well

def download_files(pkgs_list, options):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futs = [ (pkg[0], executor.submit(functools.partial(download_file, pkg, options)))
            for pkg in pkgs_list.items() ]

    for pkgname, pkg_val in futs:
        ret = pkg_val.result()

def list_dl_links(pkgs_list):
    for pkgname, pkg in pkgs_list.items():
        pkg_url, pkg_sha512 = get_dl_url(pkg)
        print(pkg_url)
    return None

def extract(pkgname):
    elem  = {}

    url = CHOCO_SEARCH_REQ.format(pkgname)
    content = requests.get(url).content.decode('utf-8')
    root = fromstringxml(bytes(content, encoding='utf-8'))

    title = root.xpath("//*[name()='d:Title']/text()")
    version = root.xpath("//*[name()='d:Version']/text()")
    links = root.xpath("//*[name()='d:DownloadCache']/text()")

    title = title[0] if len(title) == 1 else ''
    version = version[0] if len(version) == 1 else ''
    links = links[0].split('|') if len(links) == 1 else ''

    if not(title):
        print("[!] Package '%s' is not found" % pkgname)

    if title and not(links):
        print("[!] Package '%s' (entitled '%s') does not have any download link" % (pkgname, title))

    if title and version and links:
        elem['name'] = title
        dl_elem = {}
        for link in links:
            dl_url, arch_and_file, sha512 = link.split('^')
            arch, file_name = arch_and_file.split('/')
            arch = arch.lower()
            sha512 = sha512.lower()

            dl_elem[arch] = { 'dl_url': dl_url,
                              'file_name': file_name,
                              'sha512': sha512 }

        elem['dl'] = dl_elem

    return elem

def search(options, pkgs_list):
    with open(options.input_file, mode='r', encoding='utf-8') as fd_input:
        for line in fd_input:
            line = line.strip()
            if line:
                pkgname  = line
                output_dir = options.output_dir

                if ' | ' in line:
                    pkgname, output_dir = line.split(' | ')

                pkgs_list[pkgname] = {'output_dir': output_dir}

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futs = [ (pkgname, executor.submit(functools.partial(extract, pkgname)))
            for pkgname, pkg in pkgs_list.items() ]

        for pkgname, pkg_extract in futs:
            if pkgname in pkgs_list.keys():
                pkgs_list[pkgname] = {**pkgs_list[pkgname], **pkg_extract.result()}

    return None

def main():
    global parser
    options = parser.parse_args()

    pkgs_list = {}
    search(options, pkgs_list)

    if options.do_not_download:
        print()
        list_dl_links(pkgs_list)
        return None

    download_files(pkgs_list, options)

    return None

if __name__ == "__main__" :
    main()
