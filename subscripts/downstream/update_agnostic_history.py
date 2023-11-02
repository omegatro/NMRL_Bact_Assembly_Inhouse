import sys
sys.path.insert(0,'/mnt/beegfs2/home/groups/nmrl/bact_analysis/Ardetype/')
from subscripts.downstream import update_utilities as uu

#################
#Global variables
#################

full_path = uu.get_folder_path(__file__) #path to scripts
report_time = uu.get_current_timestamp()
arg_dict = {
    "k2contigs"  : ["--k2c", "Full path to the kraken2 contigs report (e.g. kraken2contigs_report.csv)"],
    "quast"      : ["--qst", "Full path to the quast report (e.g. pointfinder_report.csv)"],
    "aquamis_qc" : ["--aqc", "Full path to the quast report (e.g. pointfinder_report.csv)"]
}
proc_dict = uu.proc_dict
#setting primary key to None to ensure that records will be deduplicated only if all column value match
proc_dict['k2c'] = proc_dict['default'].copy()
proc_dict['k2c']['primary_key'] = None

##############
#Runtime logic
##############

if __name__ == '__main__':
    parser = uu.parse_arguments(arg_dict)
    uu.create_backup(full_path)
    current_tables = uu.find_current_tables(full_path, arg_dict)
    uu.update_files(arg_dict, parser, current_tables, report_time, full_path, proc_dict)
