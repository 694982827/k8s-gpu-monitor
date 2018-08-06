#!/usr/bin/env python3

import subprocess
import io
import csv
import collections
import json
import requests
import re
import os
# import threading as thd
import time
# influx db server url
posturl = 'http://10.0.4.235:9000/write?db=gpu_process'
node_name = os.getenv("NODE_NAME")
posturl   = os.getenv("INFLUXDB_URL")
print("node_name is :"+str(node_name))
print("influxdb_url is :"+ str(posturl))
if node_name == None:
    node_name = "no_name"
if posturl == None:
    posturl = 'http://10.0.4.235:9000/write?db=gpu_process'

def commandexists(shellcommand):
    status, output = subprocess.getstatusoutput(shellcommand)
    exists = status == 0
    if not exists:
        print("Could not execute: {0}".format(shellcommand))
    return exists


def command(args):
    return subprocess.check_output(args).decode()


def csvtodictdict(csvdata, colnames, keycols, fmtcols={}):
    '''
    Returns a dict of dicts from csv file with specified column names and primary key column
    accepts and optional element formatting per column as a dictionary of format functions
    '''
    fmtcols = collections.defaultdict(lambda: lambda x: x, **fmtcols)
    d = {}
    rows = csv.reader(csvdata)
    for row in rows:
        drow = {colname: fmtcols[colname](val) for colname, val in zip(colnames, row)}
        if isinstance(keycols, str):
            key = drow.pop(keycols)
        else:
            key = tuple([drow.pop(keycol) for keycol in keycols])
        d[key] = drow
    return d


def csvheaderargs(fmtcol, cols):
    return ",".join([fmtcol.format(col) for col in cols])


def commandtodictdict(baseargs, cols, keycols=None, queryargfmt="{0}", colargfmt="{0}", outputfmt={}, skipheader=False):
    queryarg = queryargfmt.format(csvheaderargs(colargfmt, cols))
    args = baseargs + [queryarg]
    # print(args)
    csvoutput = io.StringIO(command(args))
    if skipheader:
        csvoutput.readline()
    if keycols is None:
        keycols = cols[0]
    # print("sss:")
    # print(csvoutput)
    return csvtodictdict(csvoutput, cols, keycols, fmtcols=outputfmt)


def renamekeys(d, names):
    '''
    updates key names in d based on dict of old/new name pairs
    returning resulting updated dict
    '''
    for oldname, newname in names.items():
        d[newname] = d.pop(oldname)
    return d


def getContainer(containerid):
    container = command(['docker', 'inspect', containerid]).replace("\n", "").replace(" ", "");
    return json.loads(container)[0]

def main():
    # get results of all commands without container arguments
    dockerps = commandtodictdict(['docker', 'ps', '--format'],
                                 ['ID', 'Image', 'Ports'],
                                 keycols='ID',
                                 queryargfmt="'{0}'",
                                 colargfmt="{{{{.{0}}}}}",
                                 outputfmt={'ID': lambda s: s[1:]})
    dockerstats = commandtodictdict(['docker', 'stats', '--no-stream', '--format'],
                                    ['Container', 'MemUsage', 'CPUPerc'],
                                    keycols='Container',
                                    queryargfmt="'{0}'",
                                    colargfmt="{{{{.{0}}}}}",
                                    outputfmt={'Container': lambda s: s[1:]})
    unitstats = commandtodictdict(['nvidia-smi', '--format=csv'],
                                  ['gpu_uuid', 'utilization.gpu', 'utilization.memory','memory.total','memory.used','memory.free'],
                                  keycols='gpu_uuid',
                                  queryargfmt="--query-gpu={0}",
                                  outputfmt={'gpu_uuid': lambda s: s.lstrip()},
                                  skipheader=True)
    # print("un:")
    # print(unitstats)
    unitprocstats = commandtodictdict(['nvidia-smi', '--format=csv'],
                                      ['pid', 'process_name', 'gpu_uuid', 'used_memory'],
                                      keycols=['pid', 'gpu_uuid'],
                                      queryargfmt="--query-compute-apps={0}",
                                      outputfmt={'gpu_uuid': lambda s: s.lstrip()},
                                      skipheader=True)

    # map gpu_uuids to short ids in unit info rename columns
    shortunitids = {gpu_uuid: "{0}".format(shortid) for gpu_uuid, shortid in
                    zip(unitstats.keys(), range(len(unitstats)))}
    # print("short")
    # print(shortunitids)



    colnames = {'utilization.gpu': 'used_gpu'}
    unitstats = {shortunitids[gpu_uuid]: renamekeys(stats, colnames) for gpu_uuid, stats in unitstats.items()}
    # print(unitstats)
    # node level monitor
    for k in unitstats.keys():
        mem_total = int(re.sub('\D',"", unitstats[k]['memory.total']))
        mem_used = int(re.sub('\D',"",unitstats[k]['memory.used']))
        mem_util = mem_used * 100.0 / mem_total
        data = '%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s' % (
            'node_gpu,host=', node_name, ',gpu_id=', k,
            ' gpu_util=', re.sub("\D","", unitstats[k]['used_gpu']), ',mem_util=',
            mem_util,',mem_used=',re.sub('\D',"",unitstats[k]['memory.used']), ',mem_total=',
            re.sub('\D',"", unitstats[k]['memory.total']),
            ",node=\"",node_name,
            "\",gid=",k,
            ",mem_free=", re.sub('\D',"", unitstats[k]['memory.free']))
        print(data)
        response = requests.post(posturl, data=data)
        print(response.status_code)
        # print(response.headers)

    # {'0': {'utilization.memory': ' 28 %', 'used_gpu': ' 49 %'}}

    unitprocstats = {(pid, shortunitids[gpu_uuid]): stats for (pid, gpu_uuid), stats in unitprocstats.items()}

    # reassign column names to valid python variable names for formatting

    # display fmt data
    basedisplaycols = collections.OrderedDict([('Container', 12),
                                               ('Image', 18)])
    optdisplaycols = collections.OrderedDict([('pid', 7),
                                              ('gpu_uuid', 8),
                                              ('used_memory', 12),
                                              ('used_gpu', 9)])
    displaycols = collections.OrderedDict(list(basedisplaycols.items()) +
                                          list(optdisplaycols.items()))

    # display fmt strings
    basedisplayfmt = '\t'.join(['{{{0}:{1}.{1}}}'.format(col, width) for col, width in basedisplaycols.items()])
    optdisplayfmt = '\t'.join(['{{{0}:{1}.{1}}}'.format(col, width) for col, width in optdisplaycols.items()])
    displayfmt = '\t'.join([basedisplayfmt, optdisplayfmt])

    # print rows of relevant container processes
    # (everything below a bit janky in terms of argument expectations and generalization)
    dockerall = {container: {**dockerps[container], **dockerstats[container]} for container in dockerstats.keys()}
    someunitsactive = False
    # print(displayfmt.format(**{col: col for col in displaycols.keys()}))
    for container, dockerinfo in dockerall.items():
        # very particular incantation needed here for top options to function correctly:
        # https://www.projectatomic.io/blog/2016/01/understanding-docker-top-and-ps/
        pids = command(['docker', 'top', container, '-eo', 'pid']).split('\n')[1:-1]  # obviously could be a bit brittle
        # pse = commandtodictdict(['docker', 'top',container,'-eo'],
        #                   ['pid', 'time', 'cmd'],
        #                   keycols=['pid'],
        #                   queryargfmt="'{0}'",
        #                   colargfmt="{,{0}}",
        #                   outputfmt={'pid': lambda s: s[1:]})
        #                   # colargfmt="pid,time,cmd",
        #                   # outputfmt={'pid': lambda s: s[1:]})
        # print("pssss")
        # print(pse)
        containerunitstats = {(proc, unit): stat for (proc, unit), stat in unitprocstats.items() if proc in pids}
        # print(unitprocstats)
        if containerunitstats:
            someunitsactive = True
            basedisplaystr = basedisplayfmt.format(Container=container, **dockerinfo)
            # print(basedisplaystr)
            for (pid, gpu_uuid), stats in containerunitstats.items():
                # print(unitstats[gpu_uuid])
                # print("pid="+pid+";gpu_uuid="+gpu_uuid+";"+"used_memery=")
                # print(optdisplayfmt.rjust(99).format(pid=pid, gpu_uuid=gpu_uuid, **stats, **unitstats[gpu_uuid]))
                # print("used_memory="+stats['used_memory'])
                # print("process_name="+stats['process_name'])
                # print("containerid="+container)
                # print(stats)
                # print(dockerinfo['MemUsage'])
                host = node_name
                podname = "testpod"
                namespace = "10000000-name"
                labels = getContainer(container)['Config']['Labels'];
                # print(type(labels))
                # print(getContainer(container)['Config']['Labels'])
                # labels = json.loads(str(getContainer(container)['Config']['Labels']))
                if('io.kubernetes.pod.name' in labels.keys()):
                    podname = labels['io.kubernetes.pod.name']
                    namespace = labels['io.kubernetes.pod.namespace']
                pid = pid
                gpu_uuid = gpu_uuid
                # user_memory = stats['used_gpu']a
                # print(filter(str.isdigit,stats['used_memory']))
                #
                # unitstats = json.loads(unitstats)
                # print(type(unitstats))
                # data = "process,host=test,pod=".join(podname).join(",").join().join(" process_name=").join()
                data = ""
                data = '%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s%s' % ('pod_gpu,host=', host,',namespace=', namespace,',gpu=',gpu_uuid,',containerid=',container,',pod=',podname,',pid=',pid,
                    " procressname=\"",stats['process_name'].replace(" ",""),
                     "\",node=\"",node_name,
                     "\",gid=",gpu_uuid,
                    ",used_gpu=",re.sub("\D","",stats['used_memory']))
                print(data)
                response = requests.post(posturl,data=data)
                print(response.status_code)
                # print(response.headers)
    if not someunitsactive:
        print("\n\t\t no gpu units being used by docker containers ")


if __name__ == '__main__':
    # check for existence of docker and nvidia-smi commands
    if commandexists('docker') and commandexists('nvidia-smi'):
        while 1:
            main()
            time.sleep(10)
        # main()
        # thd.Timer(10, main()).start()
    else:
        print('Command(s) not found')
