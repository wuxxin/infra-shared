
{# salt states added after the transpiled butane yaml, but before inclusion of basedir/*.sls #}

{# Migration Helper for fcos/*.bu changes #}

# 24.05.20203 - test remove old system-pager.sh setting
/etc/profile.d/systemd-pager.sh:
  file:
    - absent


