import os
import logging
import sys

from avocado.core import exceptions
from avocado.utils import process

from virttest import utils_misc
from virttest import utils_package


def run(test, params, env):
    """
    A wrapper for running customized tests innested guests.

    1) Log into a guest.
    2) Run script to run tests for nested guest.
    3) Wait for script execution to complete.
    4) Pass/fail according to exit status of script.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    serial_login = params.get("serial_login", "no") == "yes"
    # make sure this path matches the path in the script
    home_path = params.get("home_path", "/home/epcci")
    result_path = os.path.join(home_path, params.get("result_path", "tests/results"))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    dst_script_path = params.get("dst_rsc_path", "/home/nested.sh")
    test_timeout = int(params.get("test_timeout", 600000))
    download_cmd = "wget %s -O %s" % (script, dst_script_path)
    run_cmd = "%s %s" % (interpreter, dst_script_path)
    result_check_cmd = "[ -d %s ]" % result_path
    cleanup_cmd = "rm -rf %s || echo 'Results folder not present,No need to clean'" % result_path

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    if serial_login:
        session = vm.wait_for_serial_login(timeout=login_timeout)
    else:
        session = vm.wait_for_login(timeout=login_timeout)

    try:
        session.cmd_status_output("dnf -y install wget", timeout=200, safe=True)
        logging.info("Starting script...")
        logging.info("Cleaning up previous results folder, if present")
        session.cmd_status_output(cleanup_cmd, print_func=logging.info,
                                  timeout=600, safe=True)
        logging.debug("Downloading script...")
        s, o = session.cmd_status_output(download_cmd, print_func=logging.info,
                                         timeout=100, safe=True)
        if s != 0:
            test.fail("Download script '%s' failed, output is: %s" % (download_cmd, o))
        try:
            logging.info("------------ Script output ------------")
            s, o = session.cmd_status_output(run_cmd, print_func=logging.info,
                                             timeout=test_timeout-1800, safe=True)

            if s != 0:
                test.fail("Run script '%s' failed, script output is: %s" % (run_cmd, o))
        finally:
            s, o = session.cmd_status_output(result_check_cmd, print_func=logging.info,
                                             timeout=100, safe=True)
            if s == 0:
                guest_results_dir = utils_misc.get_path(test.debugdir, vm.name)
                results_tarball = os.path.join(home_path, "results.tgz")
                compress_cmd = "cd %s && " % result_path
                compress_cmd += "tar cjvf %s" % results_tarball
                compress_cmd += " --exclude=*core*"
                compress_cmd += " --exclude=*crash*"
                compress_cmd += " ./*"
                session.cmd(compress_cmd, timeout=600)
                process.run("mkdir -p %s" % guest_results_dir)
                vm.copy_files_from(results_tarball, guest_results_dir)
                # cleanup results dir from guest
                clean_cmd = "rm -f %s;rm -rf %s" % (results_tarball, result_path)
                session.cmd(clean_cmd, timeout=200)
                results_tarball = os.path.basename(results_tarball)
                results_tarball = os.path.join(guest_results_dir, results_tarball)
                uncompress_cmd = "tar xjvf %s -C %s" % (results_tarball,
                                                        guest_results_dir)
                process.run(uncompress_cmd)
                process.run("rm -f %s" % results_tarball)

            logging.info("------------ End of script output ------------")


        logging.debug("nested test PASSED.")
    finally:
        session.close()
