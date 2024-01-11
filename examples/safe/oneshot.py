def provision_image(resource_name):
    "prepare an image for transfer to sdcard / usbstick"
    import infra.fcos
    from target.safe import shortname, hostname
    from infra.tools import serve_prepare, public_local_export

    serve_config = serve_prepare(resource_name)
    config = serve_config.config
    remote_url = config.config["remote_url"]
    public_ign = infra.fcos.RemoteDownloadIgnitionConfig(
        "{}_public_ignition".format(shortname), hostname, remote_url
    )

    # data to copy on sdcard
    provision = {
        "extras": infra.build.build_raspberry(),
        "image": infra.fcos.FcosImageDownloader(
            architecture="aarch64", platform="metal", image_format="raw.xz"
        ),
        "config": public_local_export(
            shortname, "{}_public.ign".format(shortname), public_ign.result
        ),
    }
    copied_image = TransferToMedium(provision)


def prepare_serve_secure_ignition(resource_name):
    from infra.tools import serve_prepare

    serve_config = serve_prepare(resource_name)
    return serve_config


def serve_secure_ignition(resource_name):
    import target.safe
    from infra.tools import serve_once

    # serve secret part of ign via serve_once and mandatory client certificate
    return serve_once(
        resource_name,
        target.safe.butane_yaml.ignition_config,
        config=prepare_serve_secure_ignition(resource_name),
    )
