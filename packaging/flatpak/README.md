# `re.fossplant.pbtk`

This folder contains a Flatpak template for the https://github.com/marin-m/pbtk GUI

## Local build instructions

## Build instructions

Build dependencies:

```
sudo apt install flatpak-builder flatpak build-essential \
    gir1.2-adw-1 gir1.2-gtk-4.0 gir1.2-soup-3.0 \
    python3-dev python3-pip appstream git
sudo snap install --classic astral-uv
```

Then, run:

```
./build.sh
```

## Utilities

These command will generate a `python3-modules.yaml` file that can serve as a template for specifying the dependencies into `re.fossplant.pbtk.yaml`:

```bash
cd
git clone git@github.com:flatpak/flatpak-builder-tools.git
git clone git@github.com:marin-m/pbtk.git

cd flatpak-builder-tools/pip
uv add PyYAML
uv sync --all-groups --frozen
source .venv/bin/activate

cd ~/pbtk/packaging/flatpak
~/flatpak-builder-tools/pip/flatpak-pip-generator --yaml --pyproject-file ~/pbtk/pyproject.toml --ignore-pkg pygobject
```
