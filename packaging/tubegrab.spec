Name:           tubegrab
Version:        1.1.1
Release:        1%{?dist}
Summary:        Download video and audio with yt-dlp and FFmpeg

License:        MIT
URL:            https://github.com/luishowin/tubegrab-linux
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
Requires:       python3
Requires:       python3-tkinter
Requires:       yt-dlp
Requires:       /usr/bin/ffmpeg

%description
TubeGrab is a small GNOME-friendly desktop utility for downloading video and
audio with yt-dlp and FFmpeg. It provides a metadata preview, a sequential
download queue, video quality selection, original-format audio, and optional
MP3 conversion.

%prep
%autosetup -n %{name}-%{version}

%build
python3 -m compileall -q tubegrab.py tubegrab

%install
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_datadir}/tubegrab
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps

cp -a tubegrab %{buildroot}%{_datadir}/tubegrab/tubegrab
find %{buildroot}%{_datadir}/tubegrab -type d -name '__pycache__' -prune -exec rm -rf {} +
find %{buildroot}%{_datadir}/tubegrab -type f -name '*.pyc' -delete

cat > %{buildroot}%{_bindir}/tubegrab <<'EOF'
#!/bin/sh
# TubeGrab launcher (installed by RPM).
export PYTHONPATH="%{_datadir}/tubegrab${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m tubegrab "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/tubegrab

sed -e 's|@EXEC@|tubegrab|g' \
    -e '/^X-TubeGrab-Managed=/d' \
    desktop/tubegrab.desktop.in > %{buildroot}%{_datadir}/applications/tubegrab.desktop

install -Dpm0644 tubegrab/assets/tubegrab.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/tubegrab.svg
for size in 16 24 32 48 64 128 256; do
    install -Dpm0644 "tubegrab/assets/icon-$size.png" \
        "%{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/tubegrab.png"
done

%post
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q %{_datadir}/applications || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor || :
fi

%postun
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q %{_datadir}/applications || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor || :
fi

%files
%{_bindir}/tubegrab
%{_datadir}/tubegrab
%{_datadir}/applications/tubegrab.desktop
%{_datadir}/icons/hicolor/scalable/apps/tubegrab.svg
%{_datadir}/icons/hicolor/16x16/apps/tubegrab.png
%{_datadir}/icons/hicolor/24x24/apps/tubegrab.png
%{_datadir}/icons/hicolor/32x32/apps/tubegrab.png
%{_datadir}/icons/hicolor/48x48/apps/tubegrab.png
%{_datadir}/icons/hicolor/64x64/apps/tubegrab.png
%{_datadir}/icons/hicolor/128x128/apps/tubegrab.png
%{_datadir}/icons/hicolor/256x256/apps/tubegrab.png
%license LICENSE
%doc README.md

%changelog
* Sun Nov 01 2026 Luis Maina <luis.howin.maina@gmail.com> - 1.1.1-1
- Update the application logo and add Fedora RPM packaging.
