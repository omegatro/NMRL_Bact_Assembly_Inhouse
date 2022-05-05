"""
This is a wrapper script of ARDETYPE pipeline.
Date: 2022-05-05
Version: 0.0
"""
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
import os, sys, re, argparse, yaml, subprocess, pandas as pd, shutil, time
from getpass import getuser


###Architecture
"""
Pipeline can start from:
    a. fastq files - run all, except demultiplexing module in core, run all or just perform assembly
    b. contigs.fasta - run only shell, relevant tip modules and shape
        shell + tip(+shape) - downstream agnostic + specific (option to report)
        shell(+shape) - downstream agnostic (option to report)
        tip(+shape) - downstream specific (option to report)
    
    *path to config file should be supplied as required argument
        template config file will be stored in github repository
        to use default settings - make a copy of the template (the file will be altered by the script)
            edit configurations in the copy of the template if customization required
            !As many options for as many tools should be accessible from config file

Pipeline output structure:
    bact_output/input_folder_name/bact_core/
        sample_id_raw fastq(excluding undetermined)
        sample_id_host_filtered fastq
        sample_id_contigs.fasta
        sample_id_contig_based_taxonomy
        sample_list (AQUAMIS format + majority genus from reads for each sample (kraken2))
        bact_shell/
            amr_pp/
            resfinder/
            kraken2_contigs/
            quast/
            mob_suite/
            rgi/
            mlst/
        bact_tip/
            based on kraken2_contigs output
            specific molecular typing for detected bacterial species
        bact_shape/
            hamronization/
            ...

from fastq:
    input - path to folder with raw fastq files
    generate sample_id_list (use aquamis script for sample id generation from different fastq formats)    qsub bact_core
        check output for each sample in id list (add status and check_note column to sample_list to indicate if check is succesful and add more information if it is not): 
            status:
                fail - cannot continue (check_note: missing <file_name> from <step_name> conducted by <module name>)
                warning - can continue, except for some steps downstream (check_note: missing <file_name> from <step_name> conducted by <module name>, affecting <affected_step_name_1>... steps)
                ok - can continue (check_note: empty)
        sample_id_raw fastq (excluding undetermined) - ok/fail
        sample_id_host_filtered fastq - ok/fail
        sample_id_contigs.fasta - ok/fail
        sample_id_contig_based_taxonomy - ok/warning
        sample_list (AQUAMIS format + majority genus from reads for each sample (kraken2)) - ok/fail
    bact_core itself will generate template string that contains all wildcards to be used by the bact_core rules
        example: '{sample_id_pattern}-{reference_sequence_pattern}-scaffolds/{sample_id_pattern}-{reference_sequence_pattern}-ragtag.scaffold.fasta' 

from contigs.fasta:
    input - path to contig file in fasta format named in format <sample_id>_contigs.fasta 
    OR 
    path to folder, containing multiple files named in format<sample_id>_contigs.fasta
    generate sample_id_list
        check file name format
            print warnings for files that does not match specified format
            if no file match format - exit with corresponding error message
            else create aquamis format table
                three columns with sample id and paths to 1st and 2nd fastq file:
                    sample	fq1	fq2
    bact_shell and other modules themselves will generate template strings that contains all wildcards to be used by the bact_shell, bact_tip & bact_shape rules
        example: '{sample_id_pattern}-{reference_sequence_pattern}-scaffolds/{sample_id_pattern}-{reference_sequence_pattern}-ragtag.scaffold.fasta' 
    if shell: qsub shell
    if tip: qsub tip
    check results
        if results contain minimum reportable amount of data and reporting option selected
            qsub shape
            check results
"""

def parse_arguments():
    """
    Parse pre-defined set of arguments from the command line, returning a namespace (object),
    that allows accessing arguments as instance variables of namespace by their full name.
    """    
    ###Parsers
    parser = argparse.ArgumentParser(description='This is a wrapper script of ARDETYPE pipeline.', formatter_class=argparse.RawTextHelpFormatter)
    req_arg_grp = parser.add_argument_group('required arguments') #to display argument under required header in help message
    
    ###generic arguments
    #####Required
    req_arg_grp.add_argument('-m', '--mode',
        metavar='\b',
        help = """Selecting mode that allows to run specific modules of the pipeline:
        all - run all modules (starting from fastq files) (not active)
        core - run only bact_core module (starting from fastq files) 
        shell - run only bact_shell module (starting from fasta file) (not active)
        shell_tip - run bact_shell and bact_tip modules (starting from fasta file) (not active)
         """,
        default=None,
        required=True)

    #####Optional
    parser.add_argument('-c', '--config', metavar='\b', help = 'Path to the config file (if not supplied, the copy of the template config_modular.yaml will be used)', default="./config_modular.yaml", required=False)
    parser.add_argument('-r', '--skip_reporting', help = 'Use this flag to skip reporting trough bact_shape module (which will run by-default with any other option)', action='store_true')
    parser.add_argument('-o', '--output_dir', metavar='\b', help = 'Path to the output directory where the results will be stored (ardetype_output/ by-default).', default="ardetype_output/", required=False)
    parser.add_argument('-s', '--install_snakemake', help = 'Use this flag to install mamba and snakemake for the current HPC user, if it is not already installed.', action='store_true')
    ###bact_core arguments
    #####Required
    req_arg_grp.add_argument('-f', '--fastq', metavar='\b', help = 'Path to directory that contains fastq files to be analysed (all files in subdirectories are included).', default=None, required=True)
    #####Optional

    ###If no command-line arguments provided - display help and stop script excecution
    if len(sys.argv)==1: 
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()
    return args


def parse_folder(folder_pth_str, file_fmt_str, substr_lst=None, regstr_lst=None):
    '''
    Given path to the folder (folder_pth_str) and file format (file_fmt_str), returns a list, 
    containing absolute paths to all files of specified format found in folder and subfolders,
    except for files that contain patterns to exclude (specified in regstr_lst) or substrings to exclude (specified in substr_lst).    
    '''
    name_series = pd.Series(dtype="str") #initialize pandas series to store path values
    for (root,dirs,files) in os.walk(folder_pth_str, topdown=True): #get list of file paths (from parent dir & subdir)
        new_files = pd.Series(files, dtype="str") #convert file names in new folder to pandas series
        new_files = new_files[new_files.str.contains(file_fmt_str)] #keep only paths to files of specifed format
        new_files = f"{os.path.abspath(root)}/"  + new_files #append absolute path to the file
        if substr_lst is not None and regstr_lst is not None and (len(substr_lst) + len(substr_lst) > 0): #if both regex and substring filters provided
            new_files = new_files[~new_files.str.contains('|'.join(substr_lst+regstr_lst))].reset_index(drop=True)
        elif regstr_lst is not None and len(regstr_lst) > 0: #if only regex filters provided
            if len(regstr_lst) > 1: #checking single filter case
                new_files = new_files[~new_files.str.contains('|'.join(regstr_lst))].reset_index(drop=True)
            else:
                new_files = new_files[~new_files.str.contains(regstr_lst[0])].reset_index(drop=True)
        elif substr_lst is not None and len(substr_lst) > 0: #if only substring filters provided
            if len(substr_lst) > 1: #checking single filter case
                new_files = new_files[~new_files.str.contains('|'.join(substr_lst))].reset_index(drop=True)
            else:
                new_files = new_files[~new_files.str.contains(substr_lst[0])].reset_index(drop=True)
        name_series = name_series.append(new_files).reset_index(drop=True) #aggregating filtered paths
    return name_series.tolist()


def create_sample_sheet(file_lst, generic_str, regex_str=None, mode=0):
    """
    Given (list) of paths to files and a generic part of the file name (e.g. _contigs.fasta or _R[1,2]_001.fastq.gz string, regex expected for fastq), mode value (int 1 for fasta, 0 (default) for fastq)
    and a sample_id regex pattern to exclude (regex string), returns pandas dataframe with sample_id column and one (fa for fasta) or two (fq1 fq2, for fastq) file path columns. 
    """
    file_series = pd.Series(file_lst, dtype="str") #to fascilitate filtering
    ss_df = pd.DataFrame(dtype="str") #to store sample sheet
    assert mode in [0,1], f"Accepted mode values are 0 for fasta and 1 for fastq: {mode} was given."

    if mode == 1:  #If function is used to produce sample sheet from fasta files
        id_extractor = lambda x: os.path.basename(x).replace(generic_str, "") #extract id from string by replacing generic part
        id_series = file_series.apply(id_extractor) 
        if regex_str is not None: 
            id_series = id_series[id_series.str.contains(regex_str)] #additional sample id filtering based on regex was requested
            assert len(id_series) > 0, 'After filtering sample ids using regex no sample ids left'
        path_series = file_series[file_series.str.contains("|".join(id_series))].reset_index(drop=True) #getting corresponding paths to fastq files
        ss_df['sample_id'], ss_df['fa'] = id_series, path_series #adding to sample sheet dataframe
        return ss_df
    
    id_extractor = lambda x: re.sub(generic_str,"",os.path.basename(x)) #extract id from string by using regex
    id_series = file_series.apply(id_extractor).drop_duplicates(keep = "first").sort_values().reset_index(drop=True)

    if regex_str is not None: #additional sample id filtering based on regex was requested
        id_series = id_series[id_series.str.contains(regex_str)]
        assert len(id_series) > 0, 'After filtering sample ids using regex no sample ids left'
    read_1_dict, read_2_dict = {}, {} #to use python mapping to ensure correspondance between id and path

    for id in id_series:
        read_files = file_series[file_series.str.contains(id)].reset_index(drop=True).sort_values().reset_index(drop=True) #extract read paths
        read_1_dict[id] = read_files[0]
        read_2_dict[id] = read_files[1]
    ss_df['sample_id'] = id_series #adding to sample sheet dataframe
    ss_df['fq1'] = ss_df['sample_id'].map(read_1_dict)
    ss_df['fq2'] = ss_df['sample_id'].map(read_2_dict)

    return ss_df


def edit_sample_sheet(ss_df, info_dict, col_name):
    """
    Given sample sheet as pandas dataframe (object), a dictionary where each sample id is matched with information to be added (dict, values to be added as one column),
    and a new column name (str), returns a pandas dataframe (object), that contains new column where new information is added to the corresponding sample id.
    """
    ss_df[col_name] = ss_df["sample_id"].map(info_dict)
    return ss_df


def check_module_output(file_list):
    """
    Given (list) of paths to expected module output files, returns a dictionary where each file path is matched with the boolean (dict)
    indicating if it is present in the file system.
    """
    return {file: os.path.isfile(file) for file in file_list}
            

def read_config(config_path):
    """
    Given path to a config.yaml file, return a dictionary (dict) form of the yaml file.
    """
    with open(os.path.abspath(config_path), 'r') as yaml_handle:
        config_dict=yaml.safe_load(yaml_handle)
    return config_dict


def edit_config(config_dict, param, new_value):
    """
    Given a dictionary (dict) that is generated from config yaml file, a parameter that needs to be changes 
    and a new value of the parameter (string), return edited dictionary were the value of specified parameter is changed.
    (Adjusted from here: https://localcoder.org/recursively-replace-dictionary-values-with-matching-key)
    """
    if param in config_dict:
        config_dict[param] = new_value
    
    for param, value in config_dict.items():
        if isinstance(value, dict):
            edit_config(value, param, new_value)
    

def write_config(config_dict, config_path):
    """
    Given a dictionary (dict) and a path to the new config file (str), check if the structure of the dictionary corresponds to the config template structure
    (read from file), and if it fits, write the contents to the new config file.
    """
    template_config_file = read_config('./config_modular.yaml')
    assert all([key in config_dict for key in template_config_file]), 'Custom config file is missing some of the keys defined in template config file, please use diff to check for difference'
    with open(config_path, "w+") as config_handle:
        yaml.dump(config_dict,config_handle)


def submit_module_job(module_name, config_path, output_dir):
    """
    Given snakemake module name (str) and path to the config file, edit submition code string (bash template, hardcoded or read from file), 
    create temporary job script (removed after submission) and perform job submition to RTU HPC cluster, returning bytestring, representing job id.
    """
    modules = {
        "core":os.path.abspath("./snakefiles/bact_core"),
        "shell":os.path.abspath("./snakefiles/bact_shell"),
        "tip":os.path.abspath("./snakefiles/bact_tip"),
        "shape":os.path.abspath("./snakefiles/bact_shape")
    }
    shutil.copy('./ardetype_jobscript.sh', f'{output_dir}ardetype_jobscript.sh')

    try:
        job_id = subprocess.check_output(['qsub', '-F', f'{modules[module_name]} {config_path}', f'{output_dir}ardetype_jobscript.sh'])
    except subprocess.CalledProcessError as msg:
        sys.exit(f"Job submission error: {msg}")
    os.system(f"rm {output_dir}ardetype_jobscript.sh")
    return job_id


def check_job_completion(job_id, module_name, job_name="ardetype", sleeping_time=150, output_dir=None):
    """
    Given job id (bytestring) and sleeping time (in seconds) between checks (int), module name (str) and job name (str),
    checks if the job is complete every n seconds. Waiting is finished when the job status is C (complete). Optionally, 
    path to output directory (str) may be given to move the file with the job standard output to it.
    """
    search_string = f"{job_id.decode('UTF-8').strip()}.*{job_name}.*{getuser()}.*[RCQ]"
    print(f'Going to sleep until ardetype/{module_name}/{job_id.decode("UTF-8").strip()} job is finished')
    while True:
        qstat = os.popen("qstat").read()
        check_job = re.search(search_string,qstat).group(0)
        print(f"{check_job} : {time.ctime(time.time())}")
        if check_job[-1] == "C":
            print(f'Finished waiting: ardetype/{module_name}/{job_id.decode("UTF-8").strip()} is complete')
            break
        time.sleep(sleeping_time)
    if output_dir is not None:
        job_report = f"{job_name}.o{job_id.decode('UTF-8').strip().split('.')[0]}"
        os.system(f"mv {job_report} {output_dir}/{module_name}_{job_name}_{job_id.decode('UTF-8').strip()}.txt")


def install_snakemake():
    '''Function is used as a wrapper for bash script that checks if snakemake is installed and installs if absent.'''
    os.system(
    '''
    eval "$(conda shell.bash hook)"
    DEFAULT_ENV=/mnt/home/$(whoami)/.conda/envs/mamba_env/envs/snakemake
    SEARCH_SNAKEMAKE=$(conda env list | grep ${DEFAULT_ENV})
    if [ ${SEARCH_SNAKEMAKE} -ef ${DEFAULT_ENV} ]; then
        echo Running with --install_snakemake flag: Snakemake is already installed for this user
    else
        echo Running with --install_snakemake flag:
        conda install -n mamba_env -c conda-forge mamba
        mamba create -c conda-forge -c bioconda -n snakemake snakemake
        conda activate snakemake
    fi    
    '''
    )


if __name__ == "__main__":
    args = parse_arguments()
    if args.install_snakemake:
        install_snakemake()
    if args.mode == "core":
        file_list = parse_folder(args.fastq,'.fastq.gz')
        try:
            fastq_formats = "(_R[1,2]_001.fastq.gz|_[1,2].fastq.gz)"
            sample_sheet = create_sample_sheet(file_list, fastq_formats, mode=0)
            os.system(f"mkdir -p {args.output_dir}")
            sample_sheet.to_csv(f"{args.output_dir}sample_sheet.csv", header=True, index=False)
        except AssertionError as msg:
            print(f"Sample sheet generation error: {msg}")

        target_list = ['sample_sheet.csv']
        template_list = [
            "_contigs.fasta",
            "_bact_reads_classified_1.fastq.gz", 
            "_bact_reads_classified_2.fastq.gz",
            "_bact_reads_unclassified_1.fastq.gz",
            "_bact_reads_unclassified_2.fastq.gz",
            "_kraken2_contigs_report.txt",
            "_kraken2_host_filtering_report.txt"
        ]
        [target_list.append(f'{args.output_dir}{id}{tmpl}') for id in sample_sheet['sample_id'] for tmpl in template_list]
        target_list.remove("sample_sheet.csv")
        config_file = read_config(args.config)
        edit_config(config_file, "core_target_files", target_list)
        edit_config(config_file, "output_directory", args.output_dir)
        try:
            write_config(config_file, f'{args.output_dir}config_core.yaml')
        except AssertionError as msg:
            print(f"Configuration file manipulation error: {msg}")
        job_id = submit_module_job('core',f'{os.path.abspath(args.output_dir)}/config_core.yaml', args.output_dir)
        check_job_completion(job_id,"bact_core",sleeping_time=5,output_dir=args.output_dir)

        check_dict = check_module_output(file_list=target_list)
        id_check_dict = {id:"" for id in sample_sheet['sample_id']}
        for file in check_dict:
            split = file.split("/",1)[1]
            id_check_dict[split.split("_",1)[0]] += f"|{split}:{check_dict[file]}"
        
        sample_sheet = edit_sample_sheet(sample_sheet, id_check_dict, "check_note")
        sample_sheet.to_csv(f"{args.output_dir}sample_sheet.csv", header=True, index=False)
    else:
        print('Sorry, other options not supported yet.')
