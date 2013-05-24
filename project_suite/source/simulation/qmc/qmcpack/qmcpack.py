
import os
from numpy import array,dot,pi
from numpy.linalg import inv,norm
from generic import obj
from physical_system import PhysicalSystem
from simulation import Simulation
from qmcpack_input import QmcpackInput,generate_qmcpack_input
from qmcpack_input import BundledQmcpackInput,TracedQmcpackInput
from qmcpack_input import loop,linear,cslinear,vmc,dmc,collection,determinantset,hamiltonian,init,pairpot
from qmcpack_input import generate_jastrows,generate_jastrow,generate_jastrow1,generate_jastrow2,generate_jastrow3
from qmcpack_input import generate_opt,generate_opts
from qmcpack_analyzer import QmcpackAnalyzer
from converters import Pw2qmcpack,Wfconvert
from sqd import Sqd
from developer import unavailable
try:
    import h5py
except ImportError:
    h5py = unavailable('h5py')
#end try



class Qmcpack(Simulation):
    input_type    = QmcpackInput
    analyzer_type = QmcpackAnalyzer
    generic_identifier = 'qmcpack'
    infile_extension   = '.in.xml'
    #application   = 'qmcapp'
    application   = 'qmcapp_complex' # always use complex version until kpoint handling is fixed
    application_properties = set(['serial','omp','mpi'])
    application_results    = set(['jastrow'])
    preserve = Simulation.preserve | set(['should_twist_average'])


    def post_init(self):
        #jtk mark
        #  may need to put this back
        #  removed because particleset is not required by qmcpack
        #   and thus the system cannot be determined without access to the h5file
        #if self.system is None:
        #    self.error('system must be specified to determine type of run')
        ##end if
        if self.system is None:
            self.warn('system must be specified to determine whether to twist average\n  proceeding under the assumption of no twist averaging')
            self.should_twist_average = False
        else:
            self.system.group_atoms()
            self.system.change_units('B')
            self.should_twist_average = len(self.system.structure.kpoints)>1
        #end if
    #end def post_init


    def propagate_identifier(self):
        self.input.simulation.project.id = self.identifier
    #end def propagate_identifier


    def check_result(self,result_name,sim):
        calculating_result = False
        if result_name=='jastrow':
            calctypes = self.input.get_output_info('calctypes')
            calculating_result = 'opt' in calctypes
        else:
            self.error('ability to check for result '+result_name+' has not been implemented')
        #end if        
        return calculating_result
    #end def check_result


    def get_result(self,result_name,sim):
        result = obj()
        analyzer = self.load_analyzer_image()
        if result_name=='jastrow':
            if not 'results' in analyzer or not 'optimization' in analyzer.results:
                self.error('analyzer did not compute results required to determine jastrow')
            #end if
            opt_file = str(analyzer.results.optimization.optimal_file)
            result.opt_file = os.path.join(self.locdir,opt_file)
        else:
            self.error('ability to get result '+result_name+' has not been implemented')
        #end if        
        del analyzer
        return result
    #end def get_result


    def incorporate_result(self,result_name,result,sim):
        input = self.input
        system = self.system
        if result_name=='orbitals':
            if isinstance(sim,Pw2qmcpack) or isinstance(sim,Wfconvert):

                h5file = result.h5file

                dsold,wavefunction = input.get('determinantset','wavefunction')
                if isinstance(wavefunction,collection):
                    if 'psi0' in wavefunction:
                        wavefunction = wavefunction.psi0
                    else:
                        wavefunction = wavefunction.list()[0]
                    #end if
                #end if
                dsnew = dsold
                dsnew.set(
                    type = 'einspline',
                    href = os.path.relpath(h5file,self.locdir)
                    )
                if system.structure.folded_structure!=None:
                    dsnew.tilematrix = array(system.structure.tmatrix)
                #end if
                defs = obj(
                    twistnum   = 0,
                    meshfactor = 1.0,
                    gpu        = False
                    )
                for var,val in defs.iteritems():
                    if not var in dsnew:
                        dsnew[var] = val
                    #end if
                #end for
                input.remove('determinantset')
                wavefunction.determinantset = dsnew

                system = self.system
                structure = system.structure
                nkpoints = len(structure.kpoints)
                if nkpoints==0:
                    self.error('system must have kpoints to assign twistnums')
                #end if
                    
                if not os.path.exists(h5file):
                    self.error('wavefunction file not found:  \n'+h5file)
                #end if

                if 'tilematrix' in system:
                    dsnew.tilematrix = array(system.tilematrix)
                #end if
                twistnums = range(len(structure.kpoints))
                if len(twistnums)>1:
                    self.twist_average(twistnums)
                else:
                    dsnew.twistnum = twistnums[0]
                #end if

            elif isinstance(sim,Sqd):

                h5file  = os.path.join(result.dir,result.h5file)
                h5file  = os.path.relpath(h5file,self.locdir)

                sqdxml_loc = os.path.join(result.dir,result.qmcfile)
                sqdxml = QmcpackInput(sqdxml_loc)

                input = self.input
                s = input.simulation
                qsys_old = s.qmcsystem
                del s.qmcsystem
                s.qmcsystem = sqdxml.qmcsystem
                if 'jastrows' in qsys_old.wavefunction:
                    s.qmcsystem.wavefunction.jastrows = qsys_old.wavefunction.jastrows
                    for jastrow in s.qmcsystem.wavefunction.jastrows:
                        if 'type' in jastrow:
                            jtype = jastrow.type.lower().replace('-','_')
                            if jtype=='one_body':
                                jastrow.source = 'atom'
                            #end if
                        #end if
                    #end for
                #end if
                s.qmcsystem.hamiltonian = hamiltonian(
                    name='h0',type='generic',target='e',
                    pairpots = [
                        pairpot(name='ElecElec',type='coulomb',source='e',target='e'),
                        pairpot(name='Coulomb' ,type='coulomb',source='atom',target='e'),
                        ]
                    )
                s.init = init(source='atom',target='e')

                abset = input.get('atomicbasisset')
                abset.href = h5file

            else:
                self.error('incorporating orbitals from '+sim.__class__.__name__+' has not been implemented')
            #end if
        elif result_name=='jastrow':
            if isinstance(sim,Qmcpack):
                opt_file = result.opt_file
                opt = QmcpackInput(opt_file)
                wavefunction = input.get('wavefunction')
                optwf = opt.qmcsystem.wavefunction
                def process_jastrow(wf):                
                    if 'jastrow' in wf:
                        js = [wf.jastrow]
                    elif 'jastrows' in wf:
                        js = wf.jastrows.values()
                    else:
                        js = []
                    #end if
                    jd = dict()
                    for j in js:
                        jtype = j.type.lower().replace('-','_').replace(' ','_')
                        jd[jtype] = j
                    #end for
                    return jd
                #end def process_jastrow
                if wavefunction==None:
                    qs = input.get('qmcsystem')
                    qs.wavefunction = optwf.copy()
                else:
                    jold = process_jastrow(wavefunction)
                    jopt = process_jastrow(optwf)
                    jnew = list(jopt.values())
                    for jtype in jold.keys():
                        if not jtype in jopt:
                            jnew.append(jold[jtype])
                        #end if
                    #end for
                    if len(jnew)==1:
                        wavefunction.jastrow = jnew[0].copy()
                    else:
                        wavefunction.jastrows = collection(jnew)
                    #end if
                #end if
                del optwf
            elif isinstance(sim,Sqd):
                wavefunction = input.get('wavefunction')
                jastrows = []
                if 'jastrows' in wavefunction:
                    for jastrow in wavefunction.jastrows:
                        jname = jastrow.name
                        if jname!='J1' and jname!='J2':
                            jastrows.append(jastrow)
                        #end if
                    #end for
                    del wavefunction.jastrows
                #end if

                ionps = input.get_ion_particlesets()
                if ionps is None or len(ionps)==0:
                    self.error('ion particleset does not seem to exist')
                elif len(ionps)==1:
                    ionps_name = list(ionps.keys())[0]
                else:
                    self.error('multiple ion species not supported for atomic calculations')
                #end if

                jastrows.extend([
                        generate_jastrow('J1','bspline',8,result.rcut,iname=ionps_name,system=self.system),
                        generate_jastrow('J2','pade',result.B)
                        ])

                wavefunction.jastrows = collection(jastrows)

            else:
                self.error('incorporating jastrow from '+sim.__class__.__name__+' has not been implemented')
            #end if
        elif result_name=='structure':
            structure = self.system.structure
            relstruct = result.structure
            structure.set(
                pos   = relstruct.positions,
                atoms = relstruct.atoms
                )
            self.input.incorporate_system(self.system)
        else:
            self.error('ability to incorporate result '+result_name+' has not been implemented')
        #end if        
    #end def incorporate_result


    def check_sim_status(self):
        outfile = os.path.join(self.locdir,self.outfile)
        errfile = os.path.join(self.locdir,self.errfile)
        fobj = open(outfile,'r')
        output = fobj.read()
        fobj.close()
        fobj = open(errfile,'r')
        errors = fobj.read()
        fobj.close()

        ran_to_end  = 'Total Execution' in output
        files_exist = True
        outfiles = self.input.get_output_info('outfiles')
        for file in outfiles:
            file_loc = os.path.join(self.locdir,file)
            files_exist = files_exist and os.path.exists(file_loc)
        #end for
            
        if ran_to_end and not files_exist:
            self.warn('run finished successfully, but output files do not seem to exist')
            print outfiles
            print os.listdir(self.locdir)
        #end if

        aborted = 'Fatal Error' in errors

        self.failed   = aborted
        self.finished = files_exist and self.job.finished and not aborted 



        #print
        #print self.__class__.__name__
        #print 'identifier ',self.identifier
        #print 'ran_to_end ',ran_to_end
        #print 'files_exist',files_exist
        #print 'aborted    ',aborted
        #print 'job done   ',self.job.finished
        #print 'finished   ',self.finished
        #print

    #end def check_sim_status


    def get_output_files(self):
        if self.should_twist_average and not isinstance(self.input,TracedQmcpackInput):
            self.twist_average(range(len(self.system.structure.kpoints)))
            br = self.bundle_request
            input = self.input.trace(br.quantity,br.values)
            input.generate_filenames(self.infile)
            self.input = input
        #end if

        output_files = self.input.get_output_info('outfiles')

        return output_files
    #end def get_output_files


    def app_command(self):
        if self.job.app_name is None:
            app_name = self.app_name
        else:
            app_name = self.job.app_name
        #end if
        return app_name+' '+self.infile      
    #end def app_command


    def twist_average(self,twistnums):
        br = obj()
        br.quantity = 'twistnum'
        br.values   = list(twistnums)
        self.bundle_request = br
        self.app_name = 'qmcapp_complex'
        #print 'twist_average'
        #print '  setting bundle request:'
        #print self.bundle_request
    #end def twist_average


    def write_prep(self):
        if self.got_dependencies:
            if 'bundle_request' in self and not isinstance(self.input,TracedQmcpackInput):
                br = self.bundle_request
                input = self.input.trace(br.quantity,br.values)
                input.generate_filenames(self.infile)
                if self.infile in self.files:
                    self.files.remove(self.infile)
                #end if
                for file in input.filenames:
                    self.files.add(file)
                #end for
                self.infile = input.filenames[-1]
                self.input  = input
                self.job.app_command = self.app_command()
            #end if
        #end if
    #end def write_prep
#end class Qmcpack




class BundledQmcpack(Qmcpack):
    infile_extension = '.in'
    application_results = set([])

    preserve = set(Simulation.preserve)
    preserve.add('sims')

    def __init__(self,**kwargs):
        if not 'sims' in kwargs:
            self.error('sims must be provided')
        #end if
        sims = kwargs['sims']
        self.sims = sims
        del kwargs['sims']
        files = set()
        for sim in sims:
            files = files | sim.files
        #end for
        kwargs['files'] = files

        inputs = []
        filenames = []
        for sim in sims:
            inputs.append(sim.input)
            filenames.append(sim.infile)
        #end for
        kwargs['input'] = BundledQmcpackInput(inputs=inputs,filenames=filenames)

        Simulation.__init__(self,**kwargs)
        deps = []
        for sim in sims:
            for dep in sim.dependencies:
                deps.append((dep.sim,'other'))
            #end for
        #end for
        self.depends(*deps)
    #end def __init__

    def propagate_identifier(self):
        for sim in self.sims:
            sim.propagate_identifier()
        #end for
    #end def propagate_identifier

    def check_result(self,result_name,sim):
        return False
    #end def check_result

    def get_result(self,result_name,sim):
        self.error(result_name+' is not calculated by BundledQmcpack')
    #end def get_result

    def check_dependencies(self,result):
        for sim in self.sims:
            sim.check_dependencies(results)
        #end for
        Simulation.check_dependencies(self,result)
    #end def check_dependencies

    def get_dependencies(self):
        for sim in self.sims:
            sim.get_dependencies()
        #end for
        Simulation.get_dependencies(self)
    #end def get_dependencies



    def check_sim_status(self):
        outfile = os.path.join(self.locdir,self.outfile)
        errfile = os.path.join(self.locdir,self.errfile)
        fobj = open(outfile,'r')
        output = fobj.read()
        fobj.close()
        fobj = open(errfile,'r')
        errors = fobj.read()
        fobj.close()

        ran_to_end  = 'Total Execution' in output
        files_exist = True
        outfiles = self.input.get_output_info('outfiles')
        for file in outfiles:
            file_loc = os.path.join(self.locdir,file)
            files_exist = files_exist and os.path.exists(file_loc)
        #end for
            
        if ran_to_end and not files_exist:
            self.warn('run finished successfully, but output files do not seem to exist')
            print outfiles
            print os.listdir(self.locdir)
        #end if

        aborted = 'Fatal Error' in errors

        self.failed   = aborted
        self.finished = files_exist and self.job.finished and not aborted 

        print
        print self.__class__.__name__
        print 'identifier ',self.identifier
        print 'ran_to_end ',ran_to_end
        print 'files_exist',files_exist
        print 'aborted    ',aborted
        print 'job done   ',self.job.finished
        print 'finished   ',self.finished
        print

        import code
        code.interact(local=dict(locals(),**globals()))

    #end def check_sim_status

#end class BundledQmcpack




def generate_qmcpack(**kwargs):
    has_input = 'input_type' in kwargs
    if has_input:
        input_type = kwargs['input_type']
        del kwargs['input_type']
    #end if
    overlapping_kw = set(['system'])
    kw = set(kwargs.keys())
    sim_kw = kw & Simulation.allowed_inputs
    inp_kw = (kw - sim_kw) | (kw & overlapping_kw)    
    sim_args = dict()
    inp_args  = dict()
    for kw in sim_kw:
        sim_args[kw] = kwargs[kw]
    #end for
    for kw in inp_kw:
        inp_args[kw] = kwargs[kw]
    #end for    
    if 'pseudos' in inp_args:
        if 'files' in sim_args:
            sim_args['files'] = list(sim_args['files'])
        else:
            sim_args['files'] = list()
        #end if
        sim_args['files'].extend(list(inp_args['pseudos']))
    #end if
    if 'system' in inp_args and isinstance(inp_args['system'],PhysicalSystem):
        inp_args['system'] = inp_args['system'].copy()
    #end if

    sim_args['input'] = generate_qmcpack_input(input_type,**inp_args)
    qmcpack = Qmcpack(**sim_args)

    return qmcpack
#end def generate_qmcpack
