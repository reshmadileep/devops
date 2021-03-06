import pandas as pd
from numpy import long
from paramiko import *
import os
from datetime import datetime
from Database_Tasks import connect_to_db, disconnect_from_db, db_objects_create_backup
import shutil
from Remote_Related_Tasks import get_file_type_to_compile, compile_reports, get_bin_file_name, execute_ssh_commands

# import config_PRE as config

# Importing the config based on environment to run
if os.getenv("ENV_TO_DEPLOY") == 'SIT':
    import config_SIT as config
elif os.getenv("ENV_TO_DEPLOY") == 'PRE':
    import config_PRE as config
elif os.getenv("ENV_TO_DEPLOY") == 'UAT':
    import config_UAT as config


def execute_ssh_command(client, command):
    print("command : " + command)
    stdin, stdout, stderr = client.exec_command(command)
    print("stdout : ")
    print(stdout.readlines())
    print("stderr : ")
    print(stderr.readlines())
    return stdout, stderr


def compare_and_locate_differences_if_any(before_list, after_list):
    if not db_exec_success_status:
        return
    list_no_difference_status = True
    before_list.sort()
    after_list.sort()
    if set(before_list) != set(after_list):
        list_no_difference_status = False
    return list_no_difference_status


def get_list_of_invalid_objects(local_path_to_create_query_file, query_to_execute):
    if not db_exec_success_status:
        return
    object_ID_list = []
    filename = 'query.sql'
    create_temp_file_with_query(local_path_to_create_query_file, query_to_execute, filename)
    out, err = execute_query_in_file_and_delete_file(ssh, local_path_to_create_query_file, filename, '$MMUSER',
                                                     '$PASSWORD')
    out_in_list_form = out.split("\r\n")
    for each_output_line in out_in_list_form:
        try:
            object_ID_list.append(long(each_output_line))
        except Exception as e:
            continue
    # print(object_ID_list)
    return object_ID_list


def remove_temp_file(local_path, filename):
    # remove file from local and remote path
    try:
        execute_ssh_command(ssh, 'rm /home/rmspre/' + filename)
        os.remove(local_path + "\\" + filename)
    except Exception as e:
        print("Error while removing file is " + str(e))


def execute_query_in_file_and_delete_file(client, local_path_of_query_file, query_filename, schema_username,
                                          schema_password):
    remote_path = "/home/rmspre/"
    copy_file_from_local_to_remote(client, local_path_of_query_file + "\\" + query_filename,
                                   remote_path + query_filename)
    out, err = execute_db_commands(client, schema_username, schema_password, remote_path, query_filename)
    remove_temp_file(local_path_of_query_file, query_filename)
    return out, err


def compile_invalid_objects(local_path_to_create_query_file, query_to_execute):
    if not db_exec_success_status:
        return
    create_temp_file_with_query(local_path_to_create_query_file, query_to_execute, 'query.sql')
    out, err = execute_query_in_file_and_delete_file(ssh, local_path_to_create_query_file, 'query.sql', '$MMUSER',
                                                     '$PASSWORD')
    result_in_array_format = out.split("\r\n")
    for result_in_each_line in result_in_array_format:
        if "ALTER " in result_in_each_line and "'ALTER'||" not in result_in_each_line:
            if 'DJ_RMS' in result_in_each_line:
                create_temp_file_with_query(local_path_to_create_query_file, result_in_each_line + "\n",
                                            "dj_rms_scripts.sql")
            elif 'ORACLE_RMS' in result_in_each_line:
                create_temp_file_with_query(local_path_to_create_query_file, result_in_each_line + "\n",
                                            "oracle_rms_scripts.sql")
            elif 'DJ_SIM' in result_in_each_line:
                create_temp_file_with_query(local_path_to_create_query_file, result_in_each_line + "\n",
                                            "dj_sim_scripts.sql")
            elif 'DJ_AIT' in result_in_each_line:
                create_temp_file_with_query(local_path_to_create_query_file, result_in_each_line + "\n",
                                            "dj_ait_scripts.sql")
    # execute DJ_RMS scripts
    execute_query_in_file_and_delete_file(ssh, local_path_to_create_query_file, "dj_rms_scripts.sql",
                                          config.DJ_RMS['username'],
                                          config.DJ_RMS['password'])
    # execute ORACLE_RMS scripts
    execute_query_in_file_and_delete_file(ssh, local_path_to_create_query_file, "oracle_rms_scripts.sql",
                                          config.ORACLE_RMS['username'],
                                          config.ORACLE_RMS['password'])
    # execute DJ_SIM scripts
    execute_query_in_file_and_delete_file(ssh, local_path_to_create_query_file, "dj_sim_scripts.sql",
                                          config.DJ_SIM['username'],
                                          config.DJ_SIM['password'])
    # execute DJ_AIT scripts
    execute_query_in_file_and_delete_file(ssh, local_path_to_create_query_file, "dj_ait_scripts.sql",
                                          config.DJ_AIT['username'],
                                          config.DJ_AIT['password'])


def compile_sqldir(client, compile_file_folder, file_name):
    out, std_error = execute_ssh_commands(client, '''
                cd {compile_file_folder}
                dos2unix {file_name}
                chmod 775 {file_name}
                exit
                '''.format(compile_file_folder=compile_file_folder, file_name=file_name))
    out = [i.decode() for i in out]
    out = '\n'.join(out)
    print(out)
    return out


def compile_form(client, compile_file_folder, file_name, compile_file_type):
    compile_command = 'compfrm' if compile_file_type == 'forms' else 'ccomp'
    environment = 'as' if compile_file_type == 'forms' else 'ds'
    out, std_error = execute_ssh_commands(client, '''
            cd {compile_file_folder}
            chgenv -g djpre rms {environment}
            {compile_command} -b {file_name}
            exit
            '''.format(compile_file_folder=compile_file_folder, file_name=file_name, environment=environment,
                       compile_command=compile_command))
    out = [i.decode() for i in out]
    out = '\n'.join(out)
    print(out)
    return out


def compiling_files_steps(file_to_compile, remote_server_compile_files_path, remote_server_bin_files_path,
                          file_to_compile_path, file_ext):
    out = ''
    # Currently supports proc and forms folder
    file_type = get_file_type_to_compile(file_ext)
    bin_file_name = get_bin_file_name(file_type, file_to_compile)
    new_bin_file_name = bin_file_name + "." + timestamp
    # Renaming files in remote server bin and compile paths
    execute_ssh_command(ssh,
                        "mv " + remote_server_compile_files_path + file_to_compile + " " + remote_server_compile_files_path + file_to_compile + "."
                        + timestamp)
    execute_ssh_command(ssh, "mv " + remote_server_bin_files_path + bin_file_name + " " + remote_server_bin_files_path +
                        new_bin_file_name)
    # Copy file to compile to remote
    copy_file_from_local_to_remote(ssh, file_to_compile_path + file_to_compile,
                                   remote_server_compile_files_path + file_to_compile)
    # Compile file
    if file_type == 'forms' or file_type == 'proc':
        out = compile_form(ssh, remote_server_compile_files_path, file_to_compile, file_type)
    elif file_type == 'reports':
        out = compile_reports(ssh, remote_server_compile_files_path, file_to_compile)
    return out


def get_list_of_files_compiled_of_each_file_type(compiling_completed_files_dictionary, filetype_for_compile,
                                                 changerequest_name):
    compiled_file_list_for_each_file_type = []
    try:
        if filetype_for_compile == 'forms':
            if len(compiling_completed_files_dictionary[changerequest_name + "/APPS"]['forms']) > 0:
                compiled_file_list_for_each_file_type = \
                    compiling_completed_files_dictionary[changerequest_name + "/APPS"]['forms']
        elif filetype_for_compile == 'proc':
            if len(compiling_completed_files_dictionary[changerequest_name + "/APPS"]['proc']) > 0:
                compiled_file_list_for_each_file_type = \
                    compiling_completed_files_dictionary[changerequest_name + "/APPS"]['proc']
        elif filetype_for_compile == 'reports':
            if len(compiling_completed_files_dictionary[changerequest_name + "/APPS"]['reports']) > 0:
                compiled_file_list_for_each_file_type = \
                    compiling_completed_files_dictionary[changerequest_name + "/APPS"]['reports']
    except Exception as e:
        print("No files compiled of the type: " + filetype_for_compile)
    finally:
        return compiled_file_list_for_each_file_type


def rollback_files_steps(compiled_files_list, filetype_for_compile, backup_file_path,
                         remote_server_compile_files_path,
                         remote_server_bin_files_path, expected_output_after_compile_operation, timestamp):
    # Initialization
    out = ''
    # Reverse the list and process
    if len(compiled_files_list) == 0:
        return
    # Rollback for proc or forms or reports
    for compiled_file in compiled_files_list:
        if os.path.exists(backup_file_path + compiled_file):
            copy_file_from_local_to_remote(ssh,
                                           backup_file_path + compiled_file,
                                           remote_server_compile_files_path + compiled_file)
            if filetype_for_compile == 'forms' or filetype_for_compile == 'proc':
                out = compile_form(ssh, remote_server_compile_files_path, compiled_file, filetype_for_compile)
            elif filetype_for_compile == 'reports':
                out = compile_reports(ssh, remote_server_compile_files_path, compiled_file)
            # If rollback fails
            if expected_output_after_compile_operation not in out:
                print(
                    "Compiling of back-up file " + compiled_file + " from trunk failed. Storing back the previously renamed file.")
                renamed_compile_filename = compiled_file + "." + timestamp
                bin_file_name = get_bin_file_name(filetype_for_compile, compiled_file)
                renamed_bin_file_name = bin_file_name + "." + timestamp
                # rename old to new files in bin and compile folders
                execute_ssh_command(ssh, "mv " + remote_server_bin_files_path +
                                    renamed_bin_file_name
                                    + " " + remote_server_bin_files_path +
                                    renamed_bin_file_name.split("." + timestamp)[0])
                execute_ssh_command(ssh,
                                    "mv " + remote_server_compile_files_path + renamed_compile_filename + " " + remote_server_compile_files_path +
                                    renamed_compile_filename.split("." + timestamp)[0])
            else:
                print("Compiling of back-up file " + compiled_file + " from trunk is successful.")
        else:
            print("Back-up file " + compiled_file + " not present in "+backup_file_path)


def rollback_compiled_files(dictionary_of_files_compiled, changerequest_name, svn_trunk_folder_path,
                            rms_remote_server_compile_files_main_path, sim_remote_server_compile_files_main_path,
                            timestamp):
    dict_keys = list(dictionary_of_files_compiled[changerequest_name + '/APPS'].keys())
    dict_keys.reverse()
    for key in dict_keys:
        dictionary_of_files_compiled[changerequest_name + '/APPS'][key].reverse()
        # Get file list to compile
        compiled_files_list = get_list_of_files_compiled_of_each_file_type(dictionary_of_files_compiled,
                                                                           key, changerequest_name)
        if key == 'forms' or key == 'proc':
            remote_server_compile_files_path, remote_server_compile_files_bin_path, expected_output = get_path_details_and_expected_output(
                rms_remote_server_compile_files_main_path, key)
        elif key == 'reports':
            remote_server_compile_files_path, remote_server_compile_files_bin_path, expected_output = get_path_details_and_expected_output(
                sim_remote_server_compile_files_main_path, key)
        if key == 'forms':
            rollback_files_steps(compiled_files_list, key,
                                 svn_trunk_folder_path + "apps\\forms\\",
                                 remote_server_compile_files_path,
                                 remote_server_compile_files_bin_path, expected_output,
                                 timestamp)
        elif key == 'proc':
            rollback_files_steps(compiled_files_list, key,
                                 svn_trunk_folder_path + "batch\\proc\\",
                                 remote_server_compile_files_path,
                                 remote_server_compile_files_bin_path, expected_output,
                                 timestamp)
        elif key == 'reports':
            rollback_files_steps(compiled_files_list, key,
                                 svn_trunk_folder_path + "apps\\reports\\",
                                 remote_server_compile_files_path,
                                 remote_server_compile_files_bin_path, expected_output,
                                 timestamp)


def get_schema_credentials(schema):
    switcher = {
        'DJ_RMS': [config.DJ_RMS['username'], config.DJ_RMS['password']],
        'ORACLE_RMS': [config.ORACLE_RMS['username'], config.ORACLE_RMS['password']],
        'DJ_SIM': [config.DJ_SIM['username'], config.DJ_SIM['password']],
        'DJ_AIT': [config.DJ_AIT['username'], config.DJ_AIT['password']]
    }
    credentials = switcher.get(schema, [])
    user_name = credentials[0]
    password = credentials[1]
    return user_name, password


def get_query(query_type):
    switcher = {
        'GET_DBA_OBJECTS': "SELECT OBJECT_ID FROM DBA_OBJECTS WHERE STATUS != 'VALID';",
        'GET_USER_OBJECTS': "SELECT OBJECT_ID FROM USER_OBJECTS WHERE STATUS != 'VALID';",
        'COMPILE_DBA_OBJECTS': "SELECT 'ALTER '|| decode(object_type, 'PACKAGE BODY', 'PACKAGE', object_type)|| ' '|| owner|| '.'|| object_name|| ' COMPILE '|| decode(object_type, 'PACKAGE BODY', 'BODY', '')|| ';' FROM dba_objects WHERE status <> 'VALID' AND object_type IN ('PROCEDURE','PACKAGE BODY','PACKAGE','TRIGGER','FUNCTION','VIEW')AND ( object_name, object_type ) NOT IN (SELECT name,type FROM dba_errors);",
        'COMPILE_USER_OBJECTS': "SELECT 'ALTER '|| decode(object_type, 'PACKAGE BODY', 'PACKAGE', object_type)|| ' '|| owner|| '.'|| object_name|| ' COMPILE '|| decode(object_type, 'PACKAGE BODY', 'BODY', '')|| ';' FROM user_objects WHERE status <> 'VALID' AND object_type IN ('PROCEDURE','PACKAGE BODY','PACKAGE','TRIGGER','FUNCTION','VIEW')AND ( object_name, object_type ) NOT IN (SELECT name,type FROM dba_errors);"
    }
    return switcher.get(query_type, "Invalid type of query")


def copy_file_from_local_to_remote(client, local_path, remote_path):
    try:
        print("copying " + local_path + " to " + remote_path)
        sftp = client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
        print("copied")
    except Exception as e:
        print(
            "Restricted unwanted copy : " + local_path + " due to "+str(e))


def delete_existing_remote_folder(path):
    sftp = ssh.open_sftp()
    try:
        sftp.stat(path)
        execute_ssh_command(ssh, 'rm -r ' + path)
    except Exception as e:
        print(path + " not previously existing.")
    sftp.close()


def remove_temp_files_created_previously(svn_cr_folder):
    # Back up folder if any created from previous run
    if os.path.exists(svn_cr_folder + "\\environment_backup"):
        shutil.rmtree(svn_cr_folder + "\\environment_backup")
    # dj_rms_scripts file if any created from previous run
    if os.path.exists(svn_cr_folder + "\\dj_rms_scripts.sql"):
        os.remove(svn_cr_folder + "\\dj_rms_scripts.sql")
    # oracle_rms_scripts file if any created from previous run
    if os.path.exists(svn_cr_folder + "\\oracle_rms_scripts.sql"):
        os.remove(svn_cr_folder + "\\oracle_rms_scripts.sql")
    # dj_sim_scripts file if any created from previous run
    if os.path.exists(svn_cr_folder + "\\dj_sim_scripts.sql"):
        os.remove(svn_cr_folder + "\\dj_sim_scripts.sql")
    # dj_ait_scripts file if any created from previous run
    if os.path.exists(svn_cr_folder + "\\dj_ait_scripts.sql"):
        os.remove(svn_cr_folder + "\\dj_ait_scripts.sql")


def create_backup_of_existing_environment(client, svn_cr_folder, cr_name):
    if not db_exec_success_status:
        return
    os.mkdir(svn_cr_folder + "\\environment_backup")
    path_to_store_backup_scripts = svn_cr_folder + "\\environment_backup"
    connection_obj = connect_to_db(config.server['db_server_host'], config.server['db_port'],
                                   config.DJ_RMS['service_name'], config.DJ_RMS['username'],
                                   config.DJ_RMS['password'])
    db_objects_create_backup(path_to_store_backup_scripts, connection_obj)
    disconnect_from_db(connection_obj)
    for file in os.listdir(path_to_store_backup_scripts):
        try:
            copy_file_from_local_to_remote(client, path_to_store_backup_scripts + '\\' + file,
                                           '/deployment/' + cr_name + '/environment_backup/' + file)
        except Exception as e:
            continue


def verify_if_file_present_in_location(list_of_file_locations_to_verify, main_folder_path,
                                       file_present_in_folder_status):
    if file_present_in_folder_status:
        for each_file_path in list_of_file_locations_to_verify:
            if not os.path.exists(main_folder_path + each_file_path.replace("/", "\\")):
                file_present_in_folder_status = False
                print("File absent in " + main_folder_path + each_file_path.replace("/", "\\"))
                break
    return file_present_in_folder_status


def extract_file_names_from_template_file_and_verify_if_files_present(file_present_in_folder_status, list_of_files,
                                                                      path_of_file):
    if not file_present_in_folder_status:
        return file_present_in_folder_status
    if not pd.isnull(list_of_files) or list_of_files != '':
        list_of_files_present = convert_to_list(list_of_files)
        if len(list_of_files_present) > 0:
            file_present_in_folder_status = verify_if_file_present_in_location(list_of_files_present,
                                                                               path_of_file,
                                                                               file_present_in_folder_status)
    return file_present_in_folder_status


def check_if_jenkinsfile_contents_exist(data_in_jenkins_file, file_present_in_folder_status):
    for sheet_name in data_in_jenkins_file.sheet_names:
        if not file_present_in_folder_status:
            break
        data_in_sheet = data_in_jenkins_file.parse(sheet_name)
        for index_value, row_value in data_in_sheet.iterrows():
            if not file_present_in_folder_status:
                break
            if sheet_name != 'APPS':
                # Checking if db folder files are present for each schema
                file_present_in_folder_status = extract_file_names_from_template_file_and_verify_if_files_present(
                    file_present_in_folder_status,
                    row_value['Values'],
                    svn_cr_folder + "\\db\\" + sheet_name + "\\")
                # Checking if db folder rollback files are present for each schema
                file_present_in_folder_status = extract_file_names_from_template_file_and_verify_if_files_present(
                    file_present_in_folder_status,
                    row_value['Rollback_Details'],
                    svn_cr_folder + "\\db\\" + sheet_name + "\\rollback\\")
            else:
                # check if forms are present
                if 'forms' in row_value['Data_to_Fill']:
                    file_present_in_folder_status = extract_file_names_from_template_file_and_verify_if_files_present(
                        file_present_in_folder_status,
                        row_value['Values'],
                        svn_cr_folder + "\\apps\\forms\\")
                # check if proc are present
                if 'proc' in row_value['Data_to_Fill']:
                    file_present_in_folder_status = extract_file_names_from_template_file_and_verify_if_files_present(
                        file_present_in_folder_status,
                        row_value['Values'],
                        svn_cr_folder + "\\batch\\proc\\")
                # check if sqldir are present
                if 'sqldir' in row_value['Data_to_Fill']:
                    file_present_in_folder_status = extract_file_names_from_template_file_and_verify_if_files_present(
                        file_present_in_folder_status,
                        row_value['Values'],
                        svn_cr_folder + "\\batch\\sqldir\\")
                # check if scripts are present
                if 'scripts' in row_value['Data_to_Fill']:
                    file_present_in_folder_status = extract_file_names_from_template_file_and_verify_if_files_present(
                        file_present_in_folder_status,
                        row_value['Values'],
                        svn_cr_folder + "\\batch\\scripts\\")
                # check if reports are present
                if 'reports' in row_value['Data_to_Fill']:
                    file_present_in_folder_status = extract_file_names_from_template_file_and_verify_if_files_present(
                        file_present_in_folder_status,
                        row_value['Values'],
                        svn_cr_folder + "\\apps\\reports\\")

    return file_present_in_folder_status


def create_folders(client, changerequest_name, svn_cr_folder):
    if not db_exec_success_status:
        return
    path = '/deployment/' + changerequest_name
    delete_existing_remote_folder(path)
    execute_ssh_command(ssh, 'mkdir ' + path)
    execute_ssh_command(ssh, 'mkdir ' + path + '/environment_backup')
    sub_directories = [x[0] for x in os.walk(svn_cr_folder)]
    list_of_folders_with_files = []
    # Creating folders in remote path
    for folder in sub_directories:
        if len(os.listdir(folder)) > 0:
            print(folder)
            folder = folder.replace(svn_cr_folder, "")
            if folder != "":
                list_of_folders_with_files.append(folder)
                execute_ssh_command(client, 'mkdir ' + path + folder.replace("\\", "/"))
    # Copy files from local to remote
    for directory_with_file in list_of_folders_with_files:
        for file in os.listdir(svn_cr_folder + directory_with_file):
            try:
                copy_file_from_local_to_remote(client, svn_cr_folder + directory_with_file + "\\" + file,
                                               path + "/" + directory_with_file.replace("\\", "/") + "/" + file)
            except Exception as e:
                continue


def execute_db_commands(client, username, password, remote_path_of_execution, db_query):
    output, error = execute_ssh_commands(client, '''
            chgenv -g djpre rms ds
            cd {path_of_execution}
            echo @{db_query} | sqlplus {username}/{password}@$ORACLE_SID
            exit
            '''.format(path_of_execution=remote_path_of_execution, db_query=db_query, username=username,
                       password=password))
    output = [i.decode() for i in output]
    output = " ".join(output)
    return output, error


def create_temp_file_with_query(local_path_to_create_file, query, filename):
    f = open(local_path_to_create_file + "\\" + filename, "a+")
    f.write(query)
    f.close()


def add_to_dictionary(main_key, inner_key, value, dictionary):
    if main_key in dictionary:
        if inner_key in dictionary[main_key]:
            dictionary[main_key][inner_key].append(value)
        else:
            dictionary[main_key][inner_key] = [value]
    else:
        dictionary[main_key] = {inner_key: [value]}


def convert_to_list(row_item):
    try:
        list_item = row_item.split('\n')
        while "" in list_item:
            list_item.remove("")
    except:
        # print("Skipping converting to list as no value to convert.")
        list_item = []
    return list_item


def db_commands_execution_each_row(commands_list, backup_list, execution_path, success_status, rollback_dictionary,
                                   executed_commands_dictionary, sheet_name):
    # Execution of scripts in each row
    for db_query in commands_list:
        dict_key_value = db_query.split('/')[0]
        if len(backup_list) > 0 and dict_key_value not in rollback_dictionary[cr_name + "/" + sheet_name]:
            rollback_dictionary[cr_name + "/" + sheet_name] = {dict_key_value: backup_list}
        output, error = execute_db_commands(ssh, username, password, execution_path, db_query)
        add_to_dictionary(cr_name + "/" + sheet_name, dict_key_value, db_query, executed_commands_dictionary)
        if "ERROR" in output or "error" in output:
            print("Script execution failed due to an error.")
            success_status = False
            break
    return success_status, executed_commands_dictionary, rollback_dictionary


def rollback_execution(scripts_execution_path, rollback_script, rollback_success):
    out, error = execute_db_commands(ssh, username, password, scripts_execution_path, rollback_script)
    if "ERROR" in out or "error" in out:
        print(
            "Recovery failed with file " + rollback_script + ". Recovery step ended.")
        rollback_success = False
    else:
        print("Recovery of file " + rollback_script + " successful.")
    return rollback_success


def db_scripts_rollback(executed_commands_dictionary, rollback_dictionary, success_status):
    if not success_status:
        rollback_success = True
        queries_executed = list(executed_commands_dictionary.keys())
        queries_executed.reverse()
        for key in queries_executed:
            each_sheet = key.split("/")[1]
            if rollback_success:
                print("Rollback started for db commands in " + each_sheet + ".")
                execution_path = cr_db_folder_path + each_sheet
                rollback_success = rollback_performed_in_each_schema(each_sheet,
                                                                     executed_commands_dictionary[key],
                                                                     rollback_dictionary[key],
                                                                     execution_path, rollback_success)
            else:
                break


def rollback_performed_in_each_schema(schema, executed_commands_dictionary, rollback_dictionary, execution_path,
                                      rollback_success):
    # Rollback mechanism : Check if rollback scripts available, else execute from trunk for each sheet
    executed_queries_list = list(executed_commands_dictionary.keys())
    executed_queries_list.reverse()
    for key in executed_queries_list:
        # Check if rollback failed at any point
        if not rollback_success:
            break
        if key in rollback_dictionary:
            print(
                "Rollback scripts available for " + key + " in rollback folder. Execution of rollback scripts started.")
            scripts_execution_path = execution_path + "/rollback"
            for rollback_script in rollback_dictionary[key]:
                if rollback_success:
                    rollback_success = rollback_execution(scripts_execution_path, rollback_script, rollback_success)
                else:
                    break
        else:
            print(
                "Fetching back up files from SVN-> Trunk as no back up available for " + key + " in excel input file.")
            executed_commands_dictionary[key].reverse()
            for fail_query in executed_commands_dictionary[key]:
                local_path = svn_trunk_folder + "db\\" + schema + "\\" + fail_query
                file_exists = os.path.exists(local_path)
                if file_exists:
                    if rollback_success:
                        execute_ssh_command(ssh,
                                            "mv " + execution_path + "/" + fail_query + " " + execution_path + "/" + fail_query + "." + timestamp)
                        local_path = svn_trunk_folder + "db\\" + schema + "\\" + fail_query.replace("/", "\\")
                        copy_file_from_local_to_remote(ssh, local_path, execution_path + "/" + fail_query)
                        rollback_success = rollback_execution(execution_path, fail_query, rollback_success)
                    else:
                        break
                else:
                    print("Skipping file " + fail_query + " as file not found in the local SVN-> Trunk.")
    return rollback_success


def get_path_details_and_expected_output(main_compile_file_path, file_type):
    comfile_file_path = ''
    bin_file_path = ''
    expected_output = ''
    if file_type == 'forms':
        comfile_file_path = main_compile_file_path + "/as/djpre/src/forms/"
        bin_file_path = main_compile_file_path + "/as/djpre/bin/"
        expected_output = 'Compile  Success.  Moved executable to $BIN'
    elif file_type == 'proc':
        comfile_file_path = main_compile_file_path + "/ds/djpre/src/proc/"
        bin_file_path = main_compile_file_path + "/ds/djpre/bin/"
        expected_output = 'Pre-ProCess, Compile, Link. Done. Moved exe to $BIN'
    elif file_type == 'reports':
        comfile_file_path = main_compile_file_path + "/as/djpre/src/reports/"
        bin_file_path = main_compile_file_path + "/as/djpre/bin/"
        expected_output = 'Compile Success.  Moved executable to $BIN'
    return comfile_file_path, bin_file_path, expected_output


cr_name_list = os.getenv("RMS_CR_IDENTIFIER").split(',')
# cr_name_list = 'CHG0012345'.split(',')
svn_folder = ".\\svn\\RMS\\"
svn_trunk_folder = svn_folder + "Trunk\\"
remote_server_compile_files_path_main_folder = "/app/retek/rms/9.0"
remote_server_compile_files_path_main_folder_for_sim = "/app/retek/sim/2.0"
timestamp = datetime.today().strftime('%Y-%m-%d-%H:%M:%S')
cr_name = ''
db_exec_success_status = True
jenkins_file_present_status = True
dba_invalid_objects_before_scripts_exec = ''
user_invalid_objects_before_scripts_exec = ''
# Initializing ssh
ssh = SSHClient()
ssh.load_system_host_keys()
ssh.set_missing_host_key_policy(AutoAddPolicy())
ssh.connect(config.server['host'], username=config.server['username'], password=config.server['password'])
# Initializing the dictionary values
rollback_dict = {}
executed_command_dict = {}
dict_of_files_compiled = {}

for cr_name in cr_name_list:
    cr_remote_folder_path = '/deployment/' + cr_name
    cr_db_folder_path = cr_remote_folder_path + '/db/'
    svn_cr_folder = svn_folder + "tags\\" + cr_name
    excel_file = svn_folder + "tags\\" + cr_name + '\\JenkinsTemplateFile.xlsx'
    # Excel data initialization
    data = ''
    # Check if Jenkins Template File Exists
    if not os.path.exists(excel_file):
        db_exec_success_status = False
        jenkins_file_present_status = False
        print("Jenkins Template File not present in the path " + svn_cr_folder)
    else:
        data = pd.ExcelFile(excel_file)
        dict_of_files_compiled[cr_name + "/APPS"] = {}
        # Check if files exist as in Jenkins File
        db_exec_success_status = check_if_jenkinsfile_contents_exist(data, jenkins_file_present_status)
    if db_exec_success_status:
        print("All files in Jenkins Template file are present in the required folders.")
        # Copying files from Jenkins server to remote server. Also remove any files if any created in the previous run
        remove_temp_files_created_previously(svn_cr_folder)
        create_folders(ssh, cr_name, svn_cr_folder)
        # Creating back up of the selected environment
        create_backup_of_existing_environment(ssh, svn_cr_folder, cr_name)
        # Storing invalid objects
        dba_invalid_objects_before_scripts_exec = get_list_of_invalid_objects(svn_cr_folder,
                                                                              get_query('GET_DBA_OBJECTS'))
        user_invalid_objects_before_scripts_exec = get_list_of_invalid_objects(svn_cr_folder,
                                                                               get_query('GET_USER_OBJECTS'))
        # Start Db scripts execution
        print("Execution of db related scripts if any started---------")
        for sheet in data.sheet_names:
            if sheet != 'APPS':
                # Check if any failure in any previous schema scripts execution
                if db_exec_success_status:
                    print("Execution of scripts if any in " + sheet + " schema started.")
                    rollback_dict[cr_name + "/" + sheet] = {}
                    executed_command_dict[cr_name + "/" + sheet] = {}
                else:
                    break
                # If no previous failure detected, proceed with each sheet -> scripts execution
                path_of_execution = cr_db_folder_path + sheet
                data_each_sheet = data.parse(sheet)
                # Adding the username and password
                username, password = get_schema_credentials(sheet)
                for index, row in data_each_sheet.iterrows():
                    # Blank or nan values check for DB queries
                    if not pd.isnull(row['Values']) or row['Values'] == '':
                        db_queries_to_execute = convert_to_list(row['Values'])
                        if len(db_queries_to_execute) == 0:
                            continue
                        if not pd.isnull(row['Rollback_Details']) or row['Rollback_Details'] == '':
                            rollback_scripts = convert_to_list(row['Rollback_Details'])
                            if len(rollback_scripts) == 0:
                                rollback_scripts = []
                        else:
                            rollback_scripts = []
                        # Check for any previous failure for scripts execution
                        if db_exec_success_status:
                            db_exec_success_status, executed_command_dict, rollback_dict = db_commands_execution_each_row(
                                db_queries_to_execute, rollback_scripts, path_of_execution,
                                db_exec_success_status, rollback_dict, executed_command_dict, sheet)
                        else:
                            print("Scripts execution over.")
                            break
                if db_exec_success_status and sheet != 'APPS':
                    print("All scripts (if any) in " + sheet + " schema are successfully executed.")

    # If no previous failures in db execution, compiling of forms or proc begins. Also check for invalid objects and compile invalid objects before deployment
    if db_exec_success_status:
        # Storing invalid objects before deployment to validate if any invalid objects need to be compiled
        dba_invalid_objects_after_scripts_exec = get_list_of_invalid_objects(svn_cr_folder,
                                                                             get_query('GET_DBA_OBJECTS'))
        user_invalid_objects_after_scripts_exec = get_list_of_invalid_objects(svn_cr_folder,
                                                                              get_query('GET_USER_OBJECTS'))
        # Compare invalid objects list
        user_if_invalid_objects_present = compare_and_locate_differences_if_any(
            user_invalid_objects_before_scripts_exec, user_invalid_objects_after_scripts_exec)
        dba_if_invalid_objects_present = compare_and_locate_differences_if_any(dba_invalid_objects_before_scripts_exec,
                                                                               dba_invalid_objects_after_scripts_exec)
        if not user_if_invalid_objects_present:
            print("Compiling invalid user objects---------------")
            # compile_invalid_objects(svn_cr_folder, get_query('COMPILE_USER_OBJECTS'))
        if not dba_if_invalid_objects_present:
            print("Compiling invalid dba objects---------------")
            # compile_invalid_objects(svn_cr_folder, get_query('COMPILE_DBA_OBJECTS'))
        # Starting compiling of objects in APPS sheet
        print("Compiling of forms/proc begins ------------")
        data_apps_sheet = data.parse('APPS')
        # Compiling of files in APPS sheet begins
        for index, row in data_apps_sheet.iterrows():
            if not db_exec_success_status:
                break
            files_to_compile_list = []
            if not pd.isnull(row['Values']) or row['Values'] != '':
                files_to_compile_list = convert_to_list(row['Values'])
                if len(files_to_compile_list) == 0:
                    continue
            for each_file in files_to_compile_list:
                print("Compiling of file " + each_file + " started.")
                # Compiling of forms begins
                if 'forms' in row['Data_to_Fill']:
                    remote_server_compile_files_folder, remote_server_compile_files_bin_folder, expected_output_after_compiling = get_path_details_and_expected_output(
                        remote_server_compile_files_path_main_folder, 'forms')
                    output = compiling_files_steps(each_file, remote_server_compile_files_folder,
                                                   remote_server_compile_files_bin_folder,
                                                   svn_cr_folder + "\\apps\\forms\\", "fmx")
                    # Adding compiled files to dictionary
                    add_to_dictionary(cr_name + '/APPS', 'forms', each_file, dict_of_files_compiled)
                    if expected_output_after_compiling not in output:
                        print("Compiling of file " + each_file + " failed.")
                        db_exec_success_status = False
                        break
                # Compiling of proc begin
                if 'proc' in row['Data_to_Fill']:
                    remote_server_compile_files_folder, remote_server_compile_files_bin_folder, expected_output_after_compiling = get_path_details_and_expected_output(
                        remote_server_compile_files_path_main_folder, 'proc')
                    output = compiling_files_steps(each_file, remote_server_compile_files_folder,
                                                   remote_server_compile_files_bin_folder,
                                                   svn_cr_folder + "\\batch\\proc\\", " ")
                    # Adding compiled files to dictionary
                    add_to_dictionary(cr_name + '/APPS', 'proc', each_file, dict_of_files_compiled)
                    if expected_output_after_compiling not in output:
                        print("Compiling of file " + each_file + " failed.")
                        db_exec_success_status = False
                        break
                # Compiling of reports begin
                if 'reports' in row['Data_to_Fill']:
                    remote_server_compile_files_folder, remote_server_compile_files_bin_folder, expected_output_after_compiling = get_path_details_and_expected_output(
                        remote_server_compile_files_path_main_folder_for_sim, 'reports')
                    output = compiling_files_steps(each_file, remote_server_compile_files_folder,
                                                   remote_server_compile_files_bin_folder,
                                                   svn_cr_folder + "\\apps\\reports\\", "rep")
                    # Adding compiled files to dictionary
                    add_to_dictionary(cr_name + '/APPS', 'reports', each_file, dict_of_files_compiled)
                    if expected_output_after_compiling not in output:
                        print("Compiling of file " + each_file + " failed.")
                        db_exec_success_status = False
                        break
                # Compiling of sqldir
                if 'sqldir' in row['Data_to_Fill']:
                    compiling_path = cr_remote_folder_path + "/batch/sqldir/"
                    compile_sqldir(ssh, compiling_path, each_file)
                # Compiling of scripts
                if 'scripts' in row['Data_to_Fill']:
                    compiling_path = cr_remote_folder_path + "/batch/scripts/"
                    compile_sqldir(ssh, compiling_path, each_file)

    if db_exec_success_status:
        print("Compiling of files completed successfully.")

if not db_exec_success_status:
    if jenkins_file_present_status:
        # Rollback of entire CR if any of the above steps fail
        print("Rollback started .........")
        # Rollback of compile files
        rollback_compiled_files(dict_of_files_compiled, cr_name, svn_trunk_folder,
                                remote_server_compile_files_path_main_folder,
                                remote_server_compile_files_path_main_folder_for_sim, timestamp)
        # Rollback of DB
        db_scripts_rollback(executed_command_dict, rollback_dict, db_exec_success_status)

if db_exec_success_status:
    print("Deployment over successfully.")
else:
    print("Deployment not over successfully.")

ssh.close()
