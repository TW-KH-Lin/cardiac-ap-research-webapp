% Fixed command-line runner for the pinned Herrera et al. 2025 MATLAB model.
args = argv();
if numel(args) ~= 41
  error('Expected: source_dir ic_file duration_ms frequency_hz AF female ISO_uM output_csv and 33 scales');
endif

source_dir = args{1};
ic_file = args{2};
duration_ms = str2double(args{3});
frequency_hz = str2double(args{4});
AF_index = str2double(args{5});
gender_flag = str2double(args{6});
ISO = str2double(args{7});
output_csv = args{8};
par_SA = zeros(1, 33);
for index = 1:33
  par_SA(index) = str2double(args{8 + index});
endfor

addpath(source_dir);
loaded = load(ic_file);
y0 = loaded.yfinal(:);
if numel(y0) ~= 184
  error('Herrera initial state must contain 184 values');
endif

female_diff = [0.85, 0.75, 0.70, 0.80, 0.75, 0.90, 1.075, 1.90];
if gender_flag == 1
  gender_param = [1, female_diff];
else
  gender_param = zeros(1, 9);
endif

cycle_length = 1000 / frequency_hz;
p = [cycle_length, AF_index, 1, ISO, 0, 0, gender_param, par_SA];
rhs = @(t, y) NH_ODE(t, y, p);
tspan = [0, duration_ms];
options = odeset('RelTol', 1e-6, 'MaxStep', 1);
[time, state] = ode15s(rhs, tspan, y0, options);
dlmwrite(output_csv, [time, state(:,39), state(:,38)], 'precision', '%.17g');
