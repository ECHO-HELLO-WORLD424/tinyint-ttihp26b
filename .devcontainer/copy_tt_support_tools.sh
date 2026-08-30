#!/bin/sh

# VS Code can forward the host's loopback proxy variables to lifecycle scripts.
# This repository is reachable directly, so do not use a host proxy here.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*'
export no_proxy='*'

if [ ! -d tt/.git ]; then
    if [ -e tt ]; then
        echo "tt exists but is not a tt-support-tools Git checkout" >&2
        exit 1
    fi
    cp -R /ttsetup/tt-support-tools tt
fi

git -c http.proxy= -c https.proxy= -C tt pull --ff-only
