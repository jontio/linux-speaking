#!/usr/bin/env bash
# Builds build/linux-speaking.vsix, the Visual Studio Code extension. A .vsix is a zip
# with the extension in an "extension" folder and two small description files.
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' vscode/package.json | head -1)
work=build/vsix
rm -rf "$work" build/linux-speaking.vsix && mkdir -p "$work/extension"
cp vscode/package.json vscode/extension.js LICENSE "$work/extension/"
cat > "$work/[Content_Types].xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension=".json" ContentType="application/json"/><Default Extension=".js" ContentType="application/javascript"/><Default Extension=".vsixmanifest" ContentType="text/xml"/><Default Extension="" ContentType="text/plain"/></Types>
XML
cat > "$work/extension.vsixmanifest" <<XML
<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="linux-speaking" Version="$version" Publisher="jontio"/>
    <DisplayName>Linux Speaking</DisplayName>
    <Description xml:space="preserve">Lets the Linux Speaking dictation engine type into the editor.</Description>
    <Categories>Other</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.75.0"/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui"/>
    </Properties>
    <License>extension/LICENSE</License>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.License" Path="extension/LICENSE" Addressable="true"/>
  </Assets>
</PackageManifest>
XML
(cd "$work" && zip -qr ../linux-speaking.vsix .)
echo "built build/linux-speaking.vsix"
