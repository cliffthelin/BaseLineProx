# Installed to /etc/profile.d/baseline-return.sh by provision.sh.
#
# The return half of BaselineOS's own (p) Proxmox action - pressing "p"
# inside Baseline runs `chvt 2`, switching the physical console's active
# VT to tty2 (systemd-logind auto-starts a getty there on first switch,
# no separate unit needs enabling). This gives any login shell on that
# console a one-word way back to tty1, instead of expecting the operator
# to remember `chvt 1` or a raw Ctrl+Alt+F1.
baseline() {
    chvt 1
}

# Only announce this on an actual physical console tty, not over SSH -
# an SSH session switching the physical console's VT out from under
# whoever is standing at the machine would be surprising, not helpful.
case "$(tty 2>/dev/null)" in
    /dev/tty[2-6])
        echo "Type 'baseline' to return to BaselineOS on tty1."
        ;;
esac
