def prepare_serve_secure_ignition(resource_name):
    from infra.tools import serve_prepare

    serve_config = serve_prepare(resource_name)
    return serve_config


def make_image(resource_name):
    "prepare target image"
    import infra.fcos
    from target.safe import shortname, hostname
    from infra.tools import public_local_export
    from infra.build import finalize_raspberry_image

    serve_config = prepare_serve_secure_ignition(resource_name)
    config = serve_config.config
    remote_url = config.config["remote_url"]
    public_ign = infra.fcos.RemoteDownloadIgnitionConfig(
        "{}_public_ignition".format(shortname), hostname, remote_url
    )

    return finalize_raspberry_image(
        image=infra.fcos.FcosImageDownloader(
            architecture="aarch64", platform="metal", image_format="raw.xz"
        ),
        config=public_local_export(
            shortname, "{}_public.ign".format(shortname), public_ign.result
        ),
    )


def provision_image(resource_name, image_resource, serial_number):
    "transfer prepared image to an sdcard / usbstick"
    from infra.tools import write_removeable

    return write_removeable(resource_name, image_resource, serial_number)


def serve_secure_ignition(resource_name):
    import target.safe
    from infra.tools import serve_once

    # serve secret part of ign via serve_once and mandatory client certificate
    return serve_once(
        resource_name,
        target.safe.butane_yaml.ignition_config,
        config=prepare_serve_secure_ignition(resource_name),
    )
