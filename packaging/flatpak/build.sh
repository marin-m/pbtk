#!/bin/bash

# Make errors fatal, print commands
set -ex

# Move to the application's root
cd "$(dirname "$0")/../.."

# Install the required Flatpak runtime and SDK
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub --user org.gnome.Sdk//51 -y
flatpak install flathub --user org.gnome.Platform//51 -y
flatpak install flathub --user org.freedesktop.Sdk.Extension.openjdk8//26.08 -y

# Build the Flathub package
rm -rf target/ # Don't copy all the planet into the Flatpak build dir
rm -rf repo/
flatpak-builder --install repo packaging/flatpak/re.fossplant.pbtk.yaml --user -y
