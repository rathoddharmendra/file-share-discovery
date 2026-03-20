FROM mcr.microsoft.com/powershell:7.4-debian-12

WORKDIR /workspace

# PSSQLite works cross-platform. ActiveDirectory module remains Windows-specific.
RUN pwsh -NoLogo -NoProfile -NonInteractive -Command \
    "Set-PSRepository PSGallery -InstallationPolicy Trusted; Install-Module PSSQLite -Scope AllUsers -Force"

COPY scripts/ps_enricher.ps1 /workspace/scripts/ps_enricher.ps1

ENTRYPOINT ["pwsh", "-NoLogo", "-NoProfile", "-File", "/workspace/scripts/ps_enricher.ps1"]
CMD ["-DbPath", "/workspace/data/shares.db"]
