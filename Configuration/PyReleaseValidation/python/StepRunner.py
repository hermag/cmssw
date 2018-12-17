import base64
import json
import multiprocessing
import os
import pprint
import random
import re
import shutil
import sys
import time
import urllib2
from datetime import datetime
from hashlib import sha1
from os import getenv
from os.path import basename, exists, join
from socket import gethostname
from subprocess import Popen

from wf import get_all_workflows_info


class StepRunner(object):

    def __init__(self, opt_object, workflows, workflowsinfofile):
        self.opt_object = opt_object
        self.wf_list = opt_object.testList
        self.dryRun = opt_object.dryRun
        self.noRun = opt_object.noRun
        self.cafVeto = opt_object.cafVeto
        self.dasOptions = opt_object.dasOptions
        self.jobReports = opt_object.jobReports
        self.nThreads = opt_object.nThreads
        self.workFlows = workflows
        # only for the step command creation, i.e. only for run_step function.
        self.aborted = False
        self.lumiRangeFile = None
        self.intRetStep = -1
        self.wfDir = ""
        self.preamble = ""
        self.manager = multiprocessing.Manager()
        self.wfinfofile = workflowsinfofile
        self.return_dict = self.manager.dict()

    def create_input_json(self):
        wf_ids = {}
        workflows = {}
        #try:
        #    workflows = get_all_workflows_info()
        #except:
        #    print "Cannot read the workflows specifications."
        #    sys.exit(2)
        try:
             with open(self.wfinfofile , 'r') as f:
                 workflows = json.load(f)
        except:
            print "Cannot read the workflows specifications."                                                                                                                                                                               
            sys.exit(2)
        wfDict = {}
        for wf in self.wf_list:
            for a_wf in self.workFlows:
                if a_wf.numId != wf:
                    continue
                else:
                    task_id = str(wf)
                    wfDict[task_id] = {}
                    if os.path.islink(a_wf.nameId):
                        continue  # ignore symlinks
                    # print '\nPreparing to generate commands for %s %s' % (a_wf.numId, a_wf.nameId)
                    wf_ids[a_wf.numId] = "%s_%s" % (a_wf.numId, a_wf.nameId)
                    sys.stdout.flush()
                    startDir = os.getcwd()
                    wfDir = str(a_wf.numId) + '_' + a_wf.nameId
                    self.wfDir = wfDir
                    if not os.path.exists(wfDir):
                        os.makedirs(wfDir)
                    elif not self.dryRun:  # clean up to allow re-running in the same overall devel area, then recreate the dir to make sure it exists
                        print "cleaning up ", wfDir, ' in ', os.getcwd()
                        shutil.rmtree(wfDir)
                        os.makedirs(wfDir)
                    preamble = 'cd ' + wfDir + '; '
                    self.preamble = preamble

                    startime = 'date %s' % time.asctime()

                    # check where we are running:
                    onCAF = False
                    if 'cms/caf/cms' in os.environ['CMS_PATH']:
                        onCAF = True
                    # current = StepRunner(a_wf, wfDir, onCAF, preamble, noRun, dryRun, cafVeto, dasOptions, jobReports, nThreads)
                    # print "MatrixRunner current ---> ", current
                    # self.threadList.append(current)
                    inFile = None
                    wf_step_cmds = []
                    wf_step_inFiles = []
                    for (istepmone, com) in enumerate(a_wf.cmds):
                        # cmd, inFile = current.run_step(istepmone + 1, com, inFile)
                        # print "a_wf.nameId ---> ", a_wf.nameId
                        cmd, inFile = self.run_step(istepmone + 1, com, inFile, a_wf.nameId, a_wf.numId)
                        wf_step_cmds.append(cmd)
                        wf_step_inFiles.append(inFile)
                        print "StepRunner ---> cmd ---> ", cmd

                    if str(sorted(workflows[task_id].keys())[0]) != "1":
                        step_id = "step1"
                        wfDict[task_id][step_id] = {}
                        wfDict[task_id][step_id]['StartTime'] = ""
                        wfDict[task_id][step_id]['EndTime'] = ""
                        wfDict[task_id][step_id]['cpuTime'] = 0.0
                        #wfDict[task_id][step_id]['nominalNumberOfEvents'] = 1
                        wfDict[task_id][step_id]['nThreadsMax'] = 1
                        wfDict[task_id][step_id]['status'] = "none"
                        wfDict[task_id][step_id]['dependsOn'] = None
                        wfDict[task_id][step_id]['cmd'] = wf_step_cmds[0]
                        wfDict[task_id][step_id]['inFile'] = wf_step_inFiles[0]
                        wfDict[task_id][step_id]['runstatus'] = None
                        wfDict[task_id][step_id]['process'] = multiprocessing.Process(
                            target=self.doCmd, args=(wf_step_cmds[0], self.dryRun))
                        wfDict[task_id][step_id]['ProcessExitCode'] = -1
                        for step in sorted(workflows[task_id].keys()):
                            step_id = "step" + str(step)
                            wfDict[task_id][step_id] = {}
                            wfDict[task_id][step_id]['StartTime'] = ""
                            wfDict[task_id][step_id]['EndTime'] = ""
                            wfDict[task_id][step_id]['cpuTime'] = workflows[task_id][step]['cpuTimePerEvent']
                            #wfDict[task_id][step_id]['nominalNumberOfEvents'] = workflows[task_id][step]['nominalNumberOfEvents']
                            wfDict[task_id][step_id]['nThreadsMax'] = workflows[task_id][step]['maxCPUs']
                            wfDict[task_id][step_id]['status'] = "none"
                            wfDict[task_id][step_id]['cmd'] = wf_step_cmds[int(step) - 1]
                            wfDict[task_id][step_id]['inFile'] = wf_step_inFiles[int(step) - 1]
                            wfDict[task_id][step_id]['runstatus'] = None
                            wfDict[task_id][step_id]['process'] = multiprocessing.Process(
                                target=self.doCmd, args=(wf_step_cmds[int(step) - 1], self.dryRun))
                            if int(workflows[task_id][step]['stepNumber']) == 1:
                                wfDict[task_id][step_id]['dependsOn'] = None
                            else:
                                wfDict[task_id][step_id]['dependsOn'] = int(workflows[task_id][step]['stepNumber']) - 1
                            wfDict[task_id][step_id]['ProcessExitCode'] = -1
                    else:
                        for step in sorted(workflows[task_id].keys()):
                            step_id = "step" + str(step)
                            wfDict[task_id][step_id] = {}
                            wfDict[task_id][step_id]['StartTime'] = ""
                            wfDict[task_id][step_id]['EndTime'] = ""
                            wfDict[task_id][step_id]['cpuTime'] = workflows[task_id][step]['cpuTimePerEvent']
                            #wfDict[task_id][step_id]['nominalNumberOfEvents'] = workflows[task_id][step]['nominalNumberOfEvents']
                            wfDict[task_id][step_id]['nThreadsMax'] = workflows[task_id][step]['maxCPUs']
                            wfDict[task_id][step_id]['status'] = "none"
                            wfDict[task_id][step_id]['cmd'] = wf_step_cmds[int(step) - 1]
                            wfDict[task_id][step_id]['inFile'] = wf_step_inFiles[int(step) - 1]
                            wfDict[task_id][step_id]['runstatus'] = None
                            wfDict[task_id][step_id]['process'] = multiprocessing.Process(
                                target=self.doCmd, args=(wf_step_cmds[int(step) - 1], self.dryRun))
                            if int(workflows[task_id][step]['stepNumber']) == 1:
                                wfDict[task_id][step_id]['dependsOn'] = None
                            else:
                                wfDict[task_id][step_id]['dependsOn'] = int(workflows[task_id][step]['stepNumber']) - 1
                            wfDict[task_id][step_id]['ProcessExitCode'] = -1
        return wfDict, wf_ids

    def doCmd(self, cmd, dryRun):
        msg = "\n# in: " + os.getcwd()
        if dryRun:
            msg += " dryRun for '"
        else:
            msg += " going to execute "
        msg += cmd.replace(';', '\n')
        # print msg
        # cmdLog = open(self.wfDir + '/cmdLog', 'a')
        # cmdLog.write(msg + '\n')
        # cmdLog.close()
        ret = 0
        if not dryRun:
            # print "WorkFlowRunner ---> not self.dryRun ---> cmd ---> ", cmd
            p = Popen(cmd, shell=True)
            ret = os.waitpid(p.pid, 0)[1]
            if ret != 0:
                print "ERROR executing ", cmd, 'ret=', ret
        self.return_dict[str(cmd)] = ret
        return ret

    def knapsack(self, knapsack_size, knapsack_weights, capacity):
        items = []
        result = []
        result_indeces = []
        ind = 0
        while ind < len(knapsack_size):
            items.append((int(knapsack_weights[ind]), int(knapsack_size[ind])))
            ind += 1

        def bestvalue(i, j):
            if i == 0:
                return 0
            value, weight = items[i - 1]
            if weight > j:
                return bestvalue(i - 1, j)
            else:
                return max(bestvalue(i - 1, j), bestvalue(i - 1, j - weight) + value)
        j = capacity
        for i in xrange(len(items), 0, -1):
            if bestvalue(i, j) != bestvalue(i - 1, j):
                result.append(items[i - 1])
                j -= items[i - 1][1]
        result.reverse()
        for item in result:
            result_indeces.append(items.index(item))
            items[items.index(item)] = (-1, -1)
        return result_indeces

    def step_statuses(self, wfs, wf_id):
        status_list = []
        for step in wfs[wf_id]:
            status_list.append(str(wfs[wf_id][step]['status']))
        return status_list

    def checker(self, wfs):
        return_code = 'end'
        return_code_1 = 'finished'
        return_code_2 = 'failed'
        for wf_id in wfs.keys():
            for step in sorted(wfs[wf_id]):
                if str(wfs[wf_id][step]['status']) != return_code_1 and str(wfs[wf_id][step]['status']) != return_code_2:
                    return str(wfs[wf_id][step]['status'])
                else:
                    continue
        return return_code

    def check_step_status(self, wfs, wf_id, step, number_of_available_cores):
        pp = pprint.PrettyPrinter(indent=4)
        if not wfs[wf_id][step]['process'].is_alive():
            wfs[wf_id][step]['ProcessExitCode'] = wfs[wf_id][step]['process'].exitcode
            if wfs[wf_id][step]['ProcessExitCode'] == 0:
                # pp.pprint(wfs)
                wfs[wf_id][step]['EndTime'] = datetime.strftime(
                    datetime.now().replace(microsecond=0), "%Y-%b-%d %H:%M:%S")                
                if self.return_dict[str(wfs[wf_id][step]['cmd'])]==0:
                    wfs[wf_id][step]['status'] = 'finished'
                    print "%s of WorkFlow %s has FINISHED. -> Exit Code: %s" % (str(step), str(wf_id), str(self.return_dict[str(wfs[wf_id][step]['cmd'])]))
                else:
                    wfs[wf_id][step]['status'] = 'failed'
                    print "%s of WorkFlow %s has FAILED. -> Exit Code: %s" % (str(step), str(wf_id), str(self.return_dict[str(wfs[wf_id][step]['cmd'])]))
                number_of_available_cores += int(wfs[wf_id][step]['nThreadsMax'])
            else:
                # pp.pprint(wfs)
                wfs[wf_id][step]['EndTime'] = datetime.strftime(
                    datetime.now().replace(microsecond=0), "%Y-%b-%d %H:%M:%S")
                wfs[wf_id][step]['status'] = 'failed'
                number_of_available_cores += int(wfs[wf_id][step]['nThreadsMax'])
                print "%s of WorkFlow %s has FAILED. -> Exit Code: %s" % (str(step), str(wf_id), str(wfs[wf_id][step]['ProcessExitCode']))
        else:
            pass
        return wfs, number_of_available_cores

    def updater(self, wfs, number_of_available_cores):
        for wf_id in wfs.keys():
            for step in wfs[wf_id]:
                try:
                    if wfs[wf_id][step]["status"] == "running":
                        wfs, number_of_available_cores = self.check_step_status(
                            wfs, wf_id, step, number_of_available_cores)
                        # elif wfs[wf_id][step]["status"] == "failed":
                    else:
                        continue
                except (KeyboardInterrupt, SystemExit):
                    print "Breaking processes"
                    sys.exit(2)
        return wfs, number_of_available_cores

    def submit(self, wfs, submission_list, number_of_available_cores):
        # collect list of required cores
        knapsack_size = []
        knapsack_weight = []
        for item in submission_list:
            knapsack_size.append(int(item[2]))
            knapsack_weight.append(float(item[3]) + 1)
        # In case we prefer to ignore the cpuTime component in knapsack algorithm
        # line 263 should be uncommented and line 260 should be commented
        #knapsack_weight = [10] * len(knapsack_size)
        capacity = number_of_available_cores
        wf_indeces = []
        wf_indeces = self.knapsack(knapsack_size, knapsack_weight, capacity)
        if len(wf_indeces) != 0:
            for wf_id in wf_indeces:
                try:
                    wfs[str(submission_list[wf_id][0])][str(submission_list[wf_id][1])][
                        'StartTime'] = datetime.strftime(datetime.now().replace(microsecond=0), "%Y-%b-%d %H:%M:%S")
                    wfs[str(submission_list[wf_id][0])][str(submission_list[wf_id][1])]['process'].start()
                    wfs[str(submission_list[wf_id][0])][str(submission_list[wf_id][1])]['status'] = 'running'
                    number_of_available_cores -= int(submission_list[wf_id][2])
                    print "%s of WorkFlow %s has started.\ncmd: %s" % (str(submission_list[wf_id][1]), str(submission_list[wf_id][0]), str(wfs[str(submission_list[wf_id][0])][str(submission_list[wf_id][1])]['cmd']))
                except:
                    wfs[str(submission_list[wf_id][0])][str(submission_list[wf_id][1])]['status'] = 'failed'
                    print "%s of WorkFlow %s has FAILED.\ncmd: %s" % (str(submission_list[wf_id][1]), str(submission_list[wf_id][0]), str(wfs[str(submission_list[wf_id][0])][str(submission_list[wf_id][1])]['cmd']))
        else:
            pass
        return wfs, number_of_available_cores

    def submitter(self, wfs, number_of_available_cores):
        # Flushing the I/O Buffer
        sys.stdout.flush()
        submission_list = []
        for wf_id in wfs.keys():
            tmp_tuple = ()
            tmp_tuple = tmp_tuple + (wf_id,)
            for step in sorted(wfs[wf_id]):
                try:
                    if wfs[wf_id][step]['status'] == 'none' and 'running' not in self.step_statuses(wfs, wf_id) and 'failed' not in self.step_statuses(wfs, wf_id):
                        tmp_tuple = tmp_tuple + (str(step),) + \
                            (wfs[wf_id][step]['nThreadsMax'],) + (wfs[wf_id][step]['cpuTime'],)
                        break
                    else:
                        continue
                except (KeyboardInterrupt, SystemExit):
                    print "Breaking processes"
                    sys.exit(2)
            if len(tmp_tuple) == 4:
                submission_list.append(tmp_tuple)
            else:
                pass
        if len(submission_list) > 0:
            wfs, number_of_available_cores = self.submit(wfs, submission_list, number_of_available_cores)
        else:
            pass
        return wfs, number_of_available_cores

    def get_report(self, wf_dict, wf_ids):
        return_string = ""
        overall_exit_string = ""
        exit_code_list = []
        passed_code_list = []
        max_number_of_steps = 0
        for wf_id in wf_dict.keys():
            max_number_of_steps = max(max_number_of_steps, len(wf_dict[wf_id].keys()))
        exit_code_list = [0] * max_number_of_steps
        passed_code_list = [0] * max_number_of_steps
        for wf_id in wf_dict.keys():
            for i in range(1, len(wf_dict[wf_id].keys()) + 1):
                exit_code_list[i - 1] += wf_dict[wf_id]['step%d' % i]['ProcessExitCode']
                if wf_dict[wf_id]['step%d' % i]['ProcessExitCode'] == 0:
                    passed_code_list[i - 1] += 1
                else:
                    pass
        for wf_id in wf_dict.keys():
            return_string += wf_ids[float(wf_id)] + " "
            for i in range(1, len(wf_dict[wf_id].keys()) + 1):
                exit_string = ""
                if wf_dict[wf_id]['step%d' % i]['status'] == 'finished':
                    return_string += "step%d-PASSED start time: %s, end time: %s; " % (
                        i, wf_dict[wf_id]['step%d' % i]['StartTime'], wf_dict[wf_id]['step%d' % i]['EndTime'])
                elif wf_dict[wf_id]['step%d' % i]['status'] == 'failed':
                    return_string += "step%d-FAILED start time: %s, end time: %s; " % (
                        i, wf_dict[wf_id]['step%d' % i]['StartTime'], wf_dict[wf_id]['step%d' % i]['EndTime'])
                else:
                    return_string += "step%d-UNKNOWN start time: %s, end time: %s; " % (
                        i, wf_dict[wf_id]['step%d' % i]['StartTime'], wf_dict[wf_id]['step%d' % i]['EndTime'])
                exit_code_list[i - 1] += wf_dict[wf_id]['step%d' % i]['ProcessExitCode']
                exit_string += str(wf_dict[wf_id]['step%d' % i]['ProcessExitCode']) + " "
            return_string += "exit: %s\n" % exit_string[:-1]
        for item in passed_code_list:
            overall_exit_string += "%d " % item
        overall_exit_string += "tests passed, "
        for item in exit_code_list:
            overall_exit_string += "%d " % item
        overall_exit_string += "failed\n"
        return_string += overall_exit_string
        return exit_code_list, overall_exit_string, return_string

    def run_step(self, istep, com, inFile, wf_nameId, wf_numId):
        def closeCmd(i, ID):
            return ' > %s 2>&1; ' % ('step%d_' % (i,) + ID + '.log ',)
        realstarttime = datetime.now()
        # isInputOk is used to keep track of the das result. In case this
        # is False we use a different error message to indicate the failed
        # das query.
        isInputOk = True
        cmd = self.preamble
        if self.aborted:
            self.npass.append(0)
            self.nfail.append(0)
            self.retStep.append(0)
            self.stat.append('NOTRUN')
            return
        if not isinstance(com, str):
            self.intRetStep = 0
            if self.cafVeto and (com.location == 'CAF' and not self.onCAF):
                print "You need to be no CAF to run", wf_numId
                self.npass.append(0)
                self.nfail.append(0)
                self.retStep.append(0)
                self.stat.append('NOTRUN')
                self.aborted = True
                return
            # create lumiRange file first so if das fails we get its error code
            cmd2 = com.lumiRanges()
            if cmd2:
                cmd2 = cmd + cmd2 + closeCmd(istep, 'lumiRanges')
                self.lumiRangeFile = 'step%d_lumiRanges.log' % (istep,)
            cmd += com.das(self.dasOptions)
            cmd += closeCmd(istep, 'dasquery')
            # don't use the file list executed, but use the das command of cmsDriver for next step
            # If the das output is not there or it's empty, consider it an
            # issue of this step, not of the next one.
            dasOutputPath = join(self.wfDir, 'step%d_dasquery.log' % (istep,))
            if not os.path.exists(dasOutputPath):
                self.intRetStep = 1
                dasOutput = None
            else:
                # We consider only the files which have at least one logical filename
                # in it. This is because sometimes das fails and still prints out junk.
                dasOutput = [l for l in open(dasOutputPath).read().split("\n") if l.startswith("/")]
            if not dasOutput:
                self.intRetStep = 1
                isInputOk = False

            inFile = 'filelist:' + basename(dasOutputPath)

            if cmd2 != None:
                return cmd2, inFile
            else:
                return cmd, inFile
            print "---"
        else:
            # chaining IO , which should be done in WF object already and not using stepX.root but <stepName>.root
            cmd += com
            if self.noRun:
                cmd += ' --no_exec'
            if inFile:  # in case previous step used DAS query (either filelist of das:)
                cmd += ' --filein ' + inFile
                inFile = None
            if self.lumiRangeFile:  # DAS query can also restrict lumi range
                cmd += ' --lumiToProcess ' + self.lumiRangeFile
                self.lumiRangeFile = None
            # 336 is an existing workflow where harvesting has to operate on AlcaReco and NOT on DQM; hard-coded..
            if 'HARVESTING' in cmd and not 134 == wf_numId and not '--filein' in cmd:
                cmd += ' --filein file:step%d_inDQM.root --fileout file:step%d.root ' % (istep - 1, istep)
            else:
                if istep != 1 and not '--filein' in cmd:
                    cmd += ' --filein file:step%s.root ' % (istep - 1,)
                if not '--fileout' in com:
                    cmd += ' --fileout file:step%s.root ' % (istep,)
            if self.jobReports:
                cmd += ' --suffix "-j JobReport%s.xml " ' % istep
            if (self.nThreads > 1) and ('HARVESTING' not in cmd):
                cmd += ' --nThreads %s' % self.nThreads
            cmd += closeCmd(istep, wf_nameId)
            # esReportWorkflow(workflow=wf_nameId,
            #                 release=getenv("CMSSW_VERSION"),
            #                 architecture=getenv("SCRAM_ARCH"),
            #                 step=istep,
            #                 command=cmd,
            #                 status="STARTED",
            #                 start_time=realstarttime.isoformat(),
            #                 workflow_id=self.wf.numId)
            # print "WorkFlowRunner L236 cmd ---> ", cmd
            return cmd, inFile
