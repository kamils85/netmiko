from __future__ import unicode_literals

import re
import time

from netmiko.base_connection import BaseConnection
from netmiko.scp_handler import BaseFileTransfer, SCPConn


class JuniperSSH(BaseConnection):
    """
    Implement methods for interacting with Juniper Networks devices.

    Disables `enable()` and `check_enable_mode()`
    methods.  Overrides several methods for Juniper-specific compatibility.
    """
    def session_preparation(self):
        """
        Prepare the session after the connection has been established.

        Disable paging (the '--more--' prompts).
        Set the base prompt for interaction ('>').
        """
        self._test_channel_read()
        self.enter_cli_mode()
        self.set_base_prompt()
        self.disable_paging(command="set cli screen-length 0")
        self.set_terminal_width(command='set cli screen-width 511')
        # Clear the read buffer
        time.sleep(.3 * self.global_delay_factor)
        self.clear_buffer()

    def enter_cli_mode(self):
        """Check if at shell prompt root@ and go into CLI."""
        delay_factor = self.select_delay_factor(delay_factor=0)
        count = 0
        cur_prompt = ''
        while count < 50:
            self.write_channel(self.RETURN)
            time.sleep(.1 * delay_factor)
            cur_prompt = self.read_channel()
            if re.search(r'root@', cur_prompt):
                self.write_channel("cli" + self.RETURN)
                time.sleep(.3 * delay_factor)
                self.clear_buffer()
                break
            elif '>' in cur_prompt or '#' in cur_prompt:
                break
            count += 1

    def check_enable_mode(self, *args, **kwargs):
        """No enable mode on Juniper."""
        pass

    def enable(self, *args, **kwargs):
        """No enable mode on Juniper."""
        pass

    def exit_enable_mode(self, *args, **kwargs):
        """No enable mode on Juniper."""
        pass

    def check_config_mode(self, check_string=']'):
        """Checks if the device is in configuration mode or not."""
        return super(JuniperSSH, self).check_config_mode(check_string=check_string)

    def config_mode(self, config_command='configure'):
        """Enter configuration mode."""
        return super(JuniperSSH, self).config_mode(config_command=config_command)

    def exit_config_mode(self, exit_config='exit configuration-mode'):
        """Exit configuration mode."""
        output = ""
        if self.check_config_mode():
            output = self.send_command_timing(exit_config, strip_prompt=False, strip_command=False)
            if 'Exit with uncommitted changes?' in output:
                output += self.send_command_timing('yes', strip_prompt=False, strip_command=False)
            if self.check_config_mode():
                raise ValueError("Failed to exit configuration mode")
        return output

    def commit(self, confirm=False, confirm_delay=None, check=False, comment='',
               and_quit=False, delay_factor=1):
        """
        Commit the candidate configuration.

        Commit the entered configuration. Raise an error and return the failure
        if the commit fails.

        Automatically enters configuration mode

        default:
            command_string = commit
        check and (confirm or confirm_dely or comment):
            Exception
        confirm_delay and no confirm:
            Exception
        confirm:
            confirm_delay option
            comment option
            command_string = commit confirmed or commit confirmed <confirm_delay>
        check:
            command_string = commit check

        """
        delay_factor = self.select_delay_factor(delay_factor)

        if check and (confirm or confirm_delay or comment):
            raise ValueError("Invalid arguments supplied with commit check")

        if confirm_delay and not confirm:
            raise ValueError("Invalid arguments supplied to commit method both confirm and check")

        # Select proper command string based on arguments provided
        command_string = 'commit'
        commit_marker = 'commit complete'
        if check:
            command_string = 'commit check'
            commit_marker = 'configuration check succeeds'
        elif confirm:
            if confirm_delay:
                command_string = 'commit confirmed ' + str(confirm_delay)
            else:
                command_string = 'commit confirmed'
            commit_marker = 'commit confirmed will be automatically rolled back in'

        # wrap the comment in quotes
        if comment:
            if '"' in comment:
                raise ValueError("Invalid comment contains double quote")
            comment = '"{0}"'.format(comment)
            command_string += ' comment ' + comment

        if and_quit:
            command_string += ' and-quit'

        # Enter config mode (if necessary)
        output = self.config_mode()
        # and_quit will get out of config mode on commit
        if and_quit:
            prompt = self.base_prompt
            output += self.send_command_expect(command_string, expect_string=prompt,
                                               strip_prompt=False,
                                               strip_command=False, delay_factor=delay_factor)
        else:
            output += self.send_command_expect(command_string, strip_prompt=False,
                                               strip_command=False, delay_factor=delay_factor)

        if commit_marker not in output:
            raise ValueError("Commit failed with the following errors:\n\n{0}"
                             .format(output))

        return output

    def strip_prompt(self, *args, **kwargs):
        """Strip the trailing router prompt from the output."""
        a_string = super(JuniperSSH, self).strip_prompt(*args, **kwargs)
        return self.strip_context_items(a_string)

    def strip_context_items(self, a_string):
        """Strip Juniper-specific output.

        Juniper will also put a configuration context:
        [edit]

        and various chassis contexts:
        {master:0}, {backup:1}

        This method removes those lines.
        """
        strings_to_strip = [
            r'\[edit.*\]',
            r'\{master:.*\}',
            r'\{backup:.*\}',
            r'\{line.*\}',
            r'\{primary.*\}',
            r'\{secondary.*\}',
        ]

        response_list = a_string.split(self.RESPONSE_RETURN)
        last_line = response_list[-1]

        for pattern in strings_to_strip:
            if re.search(pattern, last_line):
                return self.RESPONSE_RETURN.join(response_list[:-1])
        return a_string


class JuniperFileTransfer(BaseFileTransfer):
    """Juniper SCP File Transfer driver."""
    def __init__(self, ssh_conn, source_file, dest_file, file_system=None, direction='put'):
        self.ssh_ctl_chan = ssh_conn
        self.source_file = source_file
        self.dest_file = dest_file
        self.direction = direction

#        if not file_system:
#            self.file_system = self.ssh_ctl_chan._autodetect_fs()
#        else:
#            self.file_system = file_system

#        if direction == 'put':
#            self.source_md5 = self.file_md5(source_file)
#            self.file_size = os.stat(source_file).st_size
#        elif direction == 'get':
#            self.source_md5 = self.remote_md5(remote_file=source_file)
#            self.file_size = self.remote_file_size(remote_file=source_file)
#        else:
#            raise ValueError("Invalid direction specified")

    def __enter__(self):
        """Context manager setup"""
        self.establish_scp_conn()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Context manager cleanup."""
        self.close_scp_chan()

    def establish_scp_conn(self):
        """Establish SCP connection."""
        self.scp_conn = SCPConn(self.ssh_ctl_chan)

    def close_scp_chan(self):
        """Close the SCP connection to the remote network device."""
        self.scp_conn.close()
        self.scp_conn = None

    def remote_space_available(self, search_pattern=r"bytes total \((.*) bytes free\)"):
        """Return space available on remote device."""
        raise NotImplementedError

    def verify_space_available(self, search_pattern=r"bytes total \((.*) bytes free\)"):
        """Verify sufficient space is available on destination file system (return boolean)."""
        raise NotImplementedError

    def check_file_exists(self, remote_cmd=""):
        """Check if the dest_file already exists on the file system (return boolean)."""
        raise NotImplementedError

    def remote_file_size(self, remote_cmd="", remote_file=None):
        """Get the file size of the remote file."""
        raise NotImplementedError

    @staticmethod
    def process_md5(md5_output, pattern=r"= (.*)"):
        """
        Process the string to retrieve the MD5 hash

        Output from Cisco IOS (ASA is similar)
        .MD5 of flash:file_name Done!
        verify /md5 (flash:file_name) = 410db2a7015eaa42b1fe71f1bf3d59a2
        """
        raise NotImplementedError

    def compare_md5(self):
        """Compare md5 of file on network device to md5 of local file"""
        raise NotImplementedError

    def remote_md5(self, base_cmd='verify /md5', remote_file=None):
        raise NotImplementedError

    def transfer_file(self):
        """SCP transfer file."""
        if self.direction == 'put':
            self.put_file()
        elif self.direction == 'get':
            self.get_file()

    def get_file(self):
        """SCP copy the file from the remote device to local system."""
        self.scp_conn.scp_get_file(self.source_file, self.dest_file)
        self.scp_conn.close()

    def put_file(self):
        """SCP copy the file from the local system to the remote device."""
        destination = "{}/{}".format("/var/tmp", self.dest_file)
        # destination = "{}{}".format(self.file_system, self.dest_file)
        # if ':' not in destination:
        #     raise ValueError("Invalid destination file system specified")
        self.scp_conn.scp_transfer_file(self.source_file, destination)
        # Must close the SCP connection to get the file written (flush)
        self.scp_conn.close()

    def verify_file(self):
        """Verify the file has been transferred correctly."""
        raise NotImplementedError

    def enable_scp(self, cmd=None):
        raise NotImplementedError

    def disable_scp(self, cmd=None):
        raise NotImplementedError
