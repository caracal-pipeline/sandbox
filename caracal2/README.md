CARACal stimela recipes
-----------------------

Run: `stimela doc <ymlfile> <recipe>` to get documentation of the recipe file. 

List of recipe files:
- `caracal.yml` - The main caracal recipe runner
- `caracal-cabs.yml` - All the software running in containers to perform data processing
- `caracal-libs` - A list of reusable steps and libraries
- `caracal-flag.yml` - The flagging worker recipe
- `caracal-selfcal.yml` - The self calibration worker recipe
- `caracal-ddcal.yml` - The direction-dependent calibration worker recipe
- `caracal-srun.yml` - Slurm runner options (e.g. slurm: enable: true)
- `caracal-schema.yml` - The default parameters when executing the pipeline

  (also can be provided on the command line e.g. `selfcal-pa-rotate=true`)

Data combination
----------------

`stimela -C run caracal.yml concat-pointings`


Data redcution
--------------

### 1. Self-Calibration 

#### i. Initial flagging, auto-masked imaging, masking and imaging with mask to get an initial model
`./caracal.yml caracal-selfcal --step flagsummary-stats-0,flag-rfi-0,save-flags-1,flagsummary-stats-1,image-pol-0,masking-0,quality-assess-0,image-pol-1,quality-assess-1 selfcal-pa-rotate=false`

#### ii. Calibrate (delay_and_offset), image, and improve the mask
`./caracal.yml caracal-selfcal --step selcal-1,flagsummary-stats-2,image-pol-2,masking-2,quality-assess-2`

#### iii. Another round of calibration (complex-2x2), image, improve the mask and interpolate to high frequency
`./caracal.yml caracal-selfcal --step selfcal-2,flagsummary-stats-3,image-pol-3,masking-3,quality-assess-3,upsample-3,predict-3,`

NB: The step option can run specific steps of the pipeline separately. e.g. `stimela -C run caracal-flag.yml --step flagsummary-stats ms=caracal-test.ms` to run flag summary only on MS.
